"""Generation service shared by the REST API and the MCP tools.

The only sources are the predefined connectors from ucp-gen (GitHub, Jira);
a client supplies a *reference* (``owner/repo#123`` / ``PROJ-123``), never a
URL, so the server cannot be steered into arbitrary requests (no SSRF).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import ucp
from ucp_gen import build_package, build_jira_package
from ucp_gen.build import llm_docs as github_llm_docs
from ucp_gen.build_jira import llm_docs as jira_llm_docs
from ucp_gen.github import GitHubError, fetch_issue_bundle as fetch_github
from ucp_gen.jira import JiraError, fetch_issue_bundle as fetch_jira
from ucp_gen.llm import LLMConfig, LLMError, enhance

from .cache import PackageCache, package_id
from .config import Settings

logger = logging.getLogger("ucp_server")

GH_REF = re.compile(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)#(?P<number>\d+)$")
JIRA_REF = re.compile(r"^[A-Z][A-Z0-9_]*-\d+$")

SOURCES = ("github", "jira")


class InvalidRefError(ValueError):
    """The reference does not match the expected shape for the source."""


class SourceError(RuntimeError):
    """The upstream system rejected the request (auth, not found, rate limit)."""


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
    ) -> tuple[str, dict[str, Any], bool]:
        """Generate (or serve from cache) a package. Returns (id, package, from_cache)."""
        ref = ref.strip()
        cache_key = json.dumps(
            {"source": source, "ref": ref, "llm": llm, "since": since, "audience": audience},
            sort_keys=True,
        )
        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.info("cache hit for %s %s", source, ref)
            return cached.id, cached.package, True

        if source == "github":
            package, docs = self._generate_github(ref, since)
        elif source == "jira":
            package, docs = self._generate_jira(ref, since)
        else:  # request models already restrict this; belt and braces for MCP
            raise InvalidRefError(f"unknown source '{source}'; expected one of {SOURCES}")

        if llm:
            config = LLMConfig.from_env()
            try:
                package = enhance(package, docs, config)
                logger.info("LLM enhancement applied (model=%s)", config.model)
            except LLMError as exc:
                # Graceful degradation: keep the structure-only package.
                logger.warning("LLM enhancement failed, serving structural package: %s", exc)

        if audience:
            package["audience"] = {"principal": {"id": audience}}

        ucp.validate(package)  # the server must never emit an invalid package

        entry_id = package_id(source, ref)
        self.cache.put(cache_key, entry_id, package)
        logger.info("generated %s %s -> %s", source, ref, entry_id)
        return entry_id, package, False

    def _generate_github(self, ref: str, since: Optional[str]) -> tuple[dict, list[dict]]:
        match = GH_REF.match(ref)
        if not match:
            raise InvalidRefError(
                f"invalid GitHub reference '{ref}': expected owner/repo#number, e.g. pallets/flask#5961"
            )
        try:
            bundle = fetch_github(
                match["owner"], match["repo"], int(match["number"]),
                token=self.settings.github_token,
            )
        except GitHubError as exc:
            raise SourceError(str(exc)) from exc
        package = build_package(bundle, since=since)
        return package, github_llm_docs(bundle, package["generated_at"])

    def _generate_jira(self, ref: str, since: Optional[str]) -> tuple[dict, list[dict]]:
        if not JIRA_REF.match(ref):
            raise InvalidRefError(
                f"invalid Jira reference '{ref}': expected a key like PROJ-123"
            )
        try:
            bundle = fetch_jira(
                ref,
                base_url=self.settings.jira_base_url,
                email=self.settings.jira_email,
                token=self.settings.jira_api_token,
            )
        except JiraError as exc:
            raise SourceError(str(exc)) from exc
        package = build_jira_package(bundle, since=since)
        return package, jira_llm_docs(bundle, package["generated_at"])
