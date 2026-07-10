"""Generation service shared by the REST API and the MCP tools.

Predefined connectors: GitHub, Jira (ucp-gen live fetch + engine index-hit),
Confluence, Google Drive, Yandex Disk (engine index-hit only in alpha.5.1).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import ucp
from ucp_gen import build_document_package, build_package, build_jira_package
from ucp_gen.build import llm_docs as github_llm_docs
from ucp_gen.build_document import llm_docs as document_llm_docs
from ucp_gen.build_jira import llm_docs as jira_llm_docs
from ucp_gen.github import GitHubError, fetch_issue_bundle as fetch_github
from ucp_gen.jira import JiraError, fetch_issue_bundle as fetch_jira

from .oauth import get_connector_token
from ucp_gen.llm import LLMConfig, LLMError, enhance

from .cache import PackageCache, package_id
from .config import Settings

logger = logging.getLogger("ucp_server")

GH_REF = re.compile(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)#(?P<number>\d+)$")
JIRA_REF = re.compile(r"^[A-Z][A-Z0-9_]*-\d+$")
CONFLUENCE_REF = re.compile(r"^[^:]+:.+$")
GDRIVE_REF = re.compile(r"^[A-Za-z0-9_-]{10,}$")
YANDEX_REF = re.compile(r"^\d+:[a-f0-9]{32,}$")
YANDEX_PATH_REF = re.compile(r"^path:/.+")

ISSUE_SOURCES = ("github", "jira")
DOCUMENT_SOURCES = ("confluence", "gdrive", "yandex_disk")
SOURCES = ISSUE_SOURCES + DOCUMENT_SOURCES


class InvalidRefError(ValueError):
    """The reference does not match the expected shape for the source."""


class SourceError(RuntimeError):
    """The upstream system rejected the request (auth, not found, rate limit)."""


class PermissionError(RuntimeError):
    """Permission layer rejected the request (fail closed)."""


class GenerationService:
    def __init__(self, settings: Settings, cache: PackageCache):
        self.settings = settings
        self.cache = cache

    def generate(
        self,
        source: str,
        ref: str,
        *,
        llm: bool = False,
        since: Optional[str] = None,
        audience: Optional[str] = None,
        principal: Optional[str] = None,
        tenant_id: Optional[str] = None,
        tenant_slug: Optional[str] = None,
    ) -> tuple[str, dict[str, Any], bool]:
        """Generate (or serve from cache) a package. Returns (id, package, from_cache)."""
        ref = ref.strip()
        graph_version = self._graph_version(source, ref, tenant_slug=tenant_slug)
        cache_key = json.dumps(
            {
                "source": source,
                "ref": ref,
                "llm": llm,
                "since": since,
                "audience": audience,
                "graph_version": graph_version,
                "tenant_id": tenant_id,
            },
            sort_keys=True,
        )
        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.info("cache hit for %s %s", source, ref)
            package = self._apply_permissions(
                cached.package, audience, cached.id, tenant_id=tenant_id, tenant_slug=tenant_slug
            )
            return cached.id, package, True

        raw_bundle: Optional[dict[str, Any]] = None
        if source == "github":
            package, docs, raw_bundle = self._generate_github(
                ref, since, tenant_slug=tenant_slug, tenant_id=tenant_id
            )
        elif source == "jira":
            package, docs, raw_bundle = self._generate_jira(
                ref, since, tenant_slug=tenant_slug, tenant_id=tenant_id
            )
        elif source in DOCUMENT_SOURCES:
            package, docs, raw_bundle = self._generate_document(
                source, ref, since, tenant_slug=tenant_slug
            )
        else:  # request models already restrict this; belt and braces for MCP
            raise InvalidRefError(f"unknown source '{source}'; expected one of {SOURCES}")

        if llm:
            config = LLMConfig.from_env()
            try:
                package = enhance(package, docs, config)
                logger.info("LLM enhancement applied (model=%s)", config.model)
            except LLMError as exc:
                logger.warning("LLM enhancement failed, serving structural package: %s", exc)

        entry_id = package_id(source, ref)
        package = self._apply_permissions(
            package, audience, entry_id, tenant_id=tenant_id, tenant_slug=tenant_slug
        )

        ucp.validate(package)

        self.cache.put(cache_key, entry_id, package)
        logger.info("generated %s %s -> %s", source, ref, entry_id)
        if principal and raw_bundle is not None:
            self._record_token_savings(principal, source, ref, entry_id, package, raw_bundle)
        return entry_id, package, False

    def _record_token_savings(
        self,
        principal: str,
        source: str,
        ref: str,
        entry_id: str,
        package: dict[str, Any],
        bundle: dict[str, Any],
    ) -> None:
        try:
            from .token_savings import estimate_raw_tokens, get_token_savings_store

            raw_tokens = estimate_raw_tokens(source, bundle)
            ucp_tokens = ucp.estimate_tokens(ucp.render(package))
            get_token_savings_store(self.settings).record(
                principal=principal,
                source=source,
                ref=ref,
                package_id=entry_id,
                ucp_tokens=ucp_tokens,
                raw_tokens=raw_tokens,
            )
        except Exception as exc:
            logger.debug("token savings record skipped: %s", exc)

    def _apply_permissions(
        self,
        package: dict[str, Any],
        audience: Optional[str],
        entry_id: str,
        *,
        tenant_id: Optional[str] = None,
        tenant_slug: Optional[str] = None,
    ) -> dict[str, Any]:
        if not self.settings.spicedb_enabled:
            if audience:
                package = dict(package)
                package["audience"] = {"principal": {"id": audience}}
            return package
        try:
            from contextos_engine.permissions.filter import apply_permission_filter
            from contextos_engine.permissions.client import (
                PermissionDenied,
                PermissionUnavailable,
            )

            return apply_permission_filter(
                self._engine_settings(tenant_slug=tenant_slug, tenant_id=tenant_id),
                package,
                audience,
                package_id=entry_id,
            )
        except PermissionDenied as exc:
            raise PermissionError(str(exc)) from exc
        except PermissionUnavailable as exc:
            raise PermissionError(str(exc)) from exc

    def _graph_version(
        self, source: str, ref: str, *, tenant_slug: Optional[str] = None
    ) -> int:
        if not self.settings.engine_enabled or not self.settings.database_url:
            return 0
        try:
            from contextos_engine.index_store import IndexStore

            return IndexStore(
                self._engine_settings(tenant_slug=tenant_slug)
            ).get_graph_version(ref, source=source)
        except Exception as exc:
            logger.debug("graph_version lookup failed for %s %s: %s", source, ref, exc)
            return 0

    def _apply_ranking(
        self, package: dict[str, Any], *, package_id: Optional[str] = None
    ) -> dict[str, Any]:
        if not self.settings.engine_enabled or not self.settings.ranking_enabled:
            return package
        try:
            from contextos_engine.ranking import apply_ranking
            from contextos_engine.ranking.config import RankingSettings

            cfg = RankingSettings.model_construct(
                ranking_enabled=self.settings.ranking_enabled,
                ranking_top_n=self.settings.ranking_top_n,
            )
            ranked = apply_ranking(package, settings=cfg)
            ext = (ranked.get("extensions") or {}).get("contextos.ranking", {})
            n = len(ext.get("candidates") or [])
            if n:
                logger.info("ranking applied: %d candidates", n)

            if self.settings.ranking_warm_enabled:
                from .receipt_store import get_receipt_store
                from contextos_engine.ranking.warm import apply_warm_salience

                cited, ignored = get_receipt_store(self.settings).aggregate_claim_signals()
                if cited or ignored:
                    ranked = apply_warm_salience(ranked, cited=cited, ignored=ignored)
                    logger.info(
                        "warm ranking: cited=%d ignored=%d package_id=%s",
                        len(cited),
                        len(ignored),
                        package_id or "*",
                    )
            return ranked
        except Exception as exc:
            logger.warning("ranking failed: %s", exc)
            return package

    def _indexed_bundle(
        self, source: str, ref: str, *, tenant_slug: Optional[str] = None
    ) -> Optional[dict]:
        """Return a pre-indexed bundle from the engine store, if configured."""
        if not self.settings.engine_enabled or not self.settings.database_url:
            return None
        try:
            from contextos_engine.index_store import IndexStore

            store = IndexStore(self._engine_settings(tenant_slug=tenant_slug))
            if source == "yandex_disk" and ref.startswith("path:"):
                return store.get_bundle_by_disk_path(ref[5:], source=source)
            return store.get_bundle(ref, source=source)
        except Exception as exc:
            logger.warning("engine index lookup failed for %s %s: %s", source, ref, exc)
            return None

    def _indexed_github_bundle(
        self, ref: str, *, tenant_slug: Optional[str] = None
    ) -> Optional[dict]:
        return self._indexed_bundle("github", ref, tenant_slug=tenant_slug)

    def _generate_github(
        self,
        ref: str,
        since: Optional[str],
        *,
        tenant_slug: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> tuple[dict, list[dict], dict]:
        match = GH_REF.match(ref)
        if not match:
            raise InvalidRefError(
                f"invalid GitHub reference '{ref}': expected owner/repo#number, e.g. pallets/flask#5961"
            )
        bundle = self._indexed_github_bundle(ref, tenant_slug=tenant_slug)
        if bundle is not None:
            logger.info("engine index hit for github %s", ref)
        else:
            try:
                bundle = fetch_github(
                    match["owner"], match["repo"], int(match["number"]),
                    token=get_connector_token(
                        self.settings, "github", tenant_id=tenant_id
                    )
                    or self.settings.github_token,
                )
            except GitHubError as exc:
                raise SourceError(str(exc)) from exc
        package = build_package(bundle, since=since)
        if self.settings.engine_enabled and self.settings.neo4j_uri:
            package = self._enrich_from_graph("github", ref, package, since)
        package = self._apply_ranking(package, package_id=package_id("github", ref))
        return package, github_llm_docs(bundle, package["generated_at"]), bundle

    def _engine_settings(
        self, *, tenant_slug: Optional[str] = None, tenant_id: Optional[str] = None
    ):
        from contextos_engine.config import EngineSettings

        group = self.settings.graph_group_id
        if tenant_id:
            group = f"t{tenant_id}"
        return EngineSettings(
            database_url=self.settings.database_url or "",
            engine_enabled=True,
            tenant_slug=tenant_slug or self.settings.tenant_slug,
            tenant_id=tenant_id,
            neo4j_uri=self.settings.neo4j_uri or "bolt://127.0.0.1:7687",
            neo4j_user=self.settings.neo4j_user or "neo4j",
            neo4j_password=self.settings.neo4j_password or "",
            graph_group_id=group,
            spicedb_enabled=self.settings.spicedb_enabled,
            spicedb_grpc_addr=self.settings.spicedb_grpc_addr,
            spicedb_preshared_key=self.settings.spicedb_preshared_key,
            permissions_require_principal=self.settings.permissions_require_principal,
            acl_sync_default_viewer=self.settings.acl_sync_default_viewer,
            acl_sync_extra_viewers_csv=self.settings.acl_sync_extra_viewers_csv,
        )

    def _enrich_from_graph(
        self, source: str, ref: str, package: dict[str, Any], since: Optional[str]
    ) -> dict[str, Any]:
        try:
            if source == "github":
                from contextos_engine.graph.reader import (
                    fetch_github_context_diff,
                    fetch_github_graph_conflicts,
                )
            elif source == "jira":
                from contextos_engine.graph.reader import (
                    fetch_jira_context_diff,
                    fetch_jira_graph_conflicts,
                )
            else:
                return package

            from contextos_engine.graph.reader import merge_context_diff, merge_graph_conflicts

            engine_settings = self._engine_settings()
            if since:
                fetch_diff = fetch_github_context_diff if source == "github" else fetch_jira_context_diff
                graph_changes = fetch_diff(engine_settings, ref, since)
                if graph_changes:
                    logger.info(
                        "graph context_diff for %s %s: %d changes", source, ref, len(graph_changes)
                    )
                    package = merge_context_diff(package, graph_changes)
            fetch_conflicts = (
                fetch_github_graph_conflicts if source == "github" else fetch_jira_graph_conflicts
            )
            graph_conflicts = fetch_conflicts(engine_settings, ref)
            if graph_conflicts:
                logger.info(
                    "graph conflicts for %s %s: %d detected", source, ref, len(graph_conflicts)
                )
                package = merge_graph_conflicts(package, graph_conflicts)
        except Exception as exc:
            logger.warning("graph enrichment failed for %s %s: %s", source, ref, exc)
        return package

    def _generate_jira(
        self,
        ref: str,
        since: Optional[str],
        *,
        tenant_slug: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> tuple[dict, list[dict], dict]:
        if not JIRA_REF.match(ref):
            raise InvalidRefError(
                f"invalid Jira reference '{ref}': expected a key like PROJ-123"
            )
        bundle = self._indexed_bundle("jira", ref, tenant_slug=tenant_slug)
        if bundle is not None:
            logger.info("engine index hit for jira %s", ref)
        else:
            try:
                bundle = fetch_jira(
                    ref,
                    base_url=self.settings.jira_base_url,
                    email=self.settings.jira_email,
                    token=get_connector_token(self.settings, "jira", tenant_id=tenant_id)
                    or self.settings.jira_api_token,
                )
            except JiraError as exc:
                raise SourceError(str(exc)) from exc
        package = build_jira_package(bundle, since=since)
        if self.settings.engine_enabled and self.settings.neo4j_uri:
            package = self._enrich_from_graph("jira", ref, package, since)
        package = self._apply_ranking(package, package_id=package_id("jira", ref))
        return package, jira_llm_docs(bundle, package["generated_at"]), bundle

    def _validate_document_ref(self, source: str, ref: str) -> None:
        if source == "confluence" and not CONFLUENCE_REF.match(ref):
            raise InvalidRefError(
                f"invalid Confluence reference '{ref}': expected SPACE:PAGE_ID, e.g. DOCS:123456"
            )
        if source == "gdrive" and not GDRIVE_REF.match(ref):
            raise InvalidRefError(
                f"invalid Google Drive reference '{ref}': expected a file id, e.g. 1abcXYZ"
            )
        if source == "yandex_disk" and not (YANDEX_REF.match(ref) or YANDEX_PATH_REF.match(ref)):
            raise InvalidRefError(
                f"invalid Yandex Disk reference '{ref}': expected RESOURCE_ID:HASH or path:/disk/file.pdf"
            )

    def _generate_document(
        self,
        source: str,
        ref: str,
        since: Optional[str],
        *,
        tenant_slug: Optional[str] = None,
    ) -> tuple[dict, list[dict], dict]:
        self._validate_document_ref(source, ref)
        bundle = self._indexed_bundle(source, ref, tenant_slug=tenant_slug)
        if bundle is None:
            raise SourceError(
                f"document not found in engine index: {source} {ref} (run sync first)"
            )
        logger.info("engine index hit for %s %s", source, ref)
        package = build_document_package(bundle, since=since)
        package = self._apply_ranking(package, package_id=package_id(source, ref))
        return package, document_llm_docs(bundle, package["generated_at"]), bundle
