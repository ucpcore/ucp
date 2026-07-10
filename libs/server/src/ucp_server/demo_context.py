"""Onboarding demo: token comparison, package insights, agent prompts."""
from __future__ import annotations

from typing import Any, Optional

from .cache import PackageCache
from .config import Settings
from .connector_config import get_scope, list_connectors
from .token_savings import BENCHMARK_EXAMPLE, get_token_savings_store

AGENT_PROMPTS = {
    "cursor": {
        "label": "Cursor",
        "slash": "/ucp {ref}",
        "hint": "Type in chat after MCP OAuth — or use the ucp slash command.",
    },
    "claude_code": {
        "label": "Claude Code",
        "slash": "/ucp {ref}",
        "hint": "Run in terminal after `claude mcp login` — same slash command if installed.",
    },
}


def _package_insights(package: dict[str, Any]) -> dict[str, Any]:
    decisions = package.get("decisions") or []
    conflicts = package.get("conflicts") or []
    return {
        "decisions_count": len(decisions),
        "conflicts_count": len(conflicts),
        "decisions": [
            {
                "title": str(d.get("title") or d.get("summary") or "Decision")[:120],
                "status": str(d.get("status") or "unknown"),
            }
            for d in decisions[:5]
        ],
        "conflicts": [
            {
                "summary": str(c.get("summary") or c.get("description") or "Conflict")[:120],
            }
            for c in conflicts[:3]
        ],
    }


def _scope_prefixes(settings: Settings) -> list[str]:
    prefixes: list[str] = []
    for provider in ("github", "jira"):
        scope = get_scope(settings, provider)
        if provider == "github":
            for repo in scope.get("repos") or []:
                if repo:
                    prefixes.append(f"{repo}#")
        elif provider == "jira":
            for project in scope.get("projects") or []:
                if project:
                    prefixes.append(f"{project}-")
    return prefixes


def _benchmark_comparison() -> dict[str, Any]:
    return {
        "mode": "benchmark",
        "ref": BENCHMARK_EXAMPLE["ref"],
        "raw_tokens": BENCHMARK_EXAMPLE["raw_tokens"],
        "ucp_tokens": BENCHMARK_EXAMPLE["ucp_tokens"],
        "tokens_saved": BENCHMARK_EXAMPLE["tokens_saved"],
        "reduction_pct": BENCHMARK_EXAMPLE["reduction_pct"],
        "label": "Published benchmark (vscode#519 mega-thread)",
    }


def _last_comparison(last: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": "yours",
        "ref": last.get("ref"),
        "source": last.get("source"),
        "raw_tokens": int(last.get("raw_tokens") or 0),
        "ucp_tokens": int(last.get("ucp_tokens") or 0),
        "tokens_saved": int(last.get("tokens_saved") or 0),
        "reduction_pct": int(last.get("reduction_pct") or 0),
        "label": "Your last generated package",
    }


def _total_comparison(summary: dict[str, Any]) -> Optional[dict[str, Any]]:
    if int(summary.get("packages") or 0) <= 0:
        return None
    raw = int(summary.get("raw_tokens") or 0)
    ucp = int(summary.get("ucp_tokens") or 0)
    saved = int(summary.get("tokens_saved") or 0)
    return {
        "mode": "total",
        "ref": None,
        "raw_tokens": raw,
        "ucp_tokens": ucp,
        "tokens_saved": saved,
        "reduction_pct": int(summary.get("avg_reduction_pct") or 0),
        "label": f"Total saved ({int(summary.get('packages') or 0)} packages)",
        "packages": int(summary.get("packages") or 0),
    }


def _indexed_refs(settings: Settings) -> list[dict[str, Any]]:
    if not settings.engine_enabled or not settings.database_url:
        return []
    try:
        from contextos_engine.config import EngineSettings
        from contextos_engine.index_store import IndexStore

        engine_settings = EngineSettings.model_construct(
            engine_enabled=True,
            database_url=settings.database_url,
        )
        prefixes = _scope_prefixes(settings)
        return IndexStore(engine_settings).list_recent_refs(
            limit=20,
            scope_prefixes=prefixes or None,
        )
    except Exception:
        return []


def _suggested_ref(settings: Settings, indexed_refs: list[dict[str, Any]]) -> Optional[str]:
    if indexed_refs:
        return str(indexed_refs[0].get("ref") or "") or None
    connectors = list_connectors(settings).get("connectors") or []
    for provider in ("github", "jira"):
        spec = next((c for c in connectors if c.get("provider") == provider), None)
        if not spec:
            continue
        scope = spec.get("scope") or {}
        if provider == "github":
            repos = scope.get("repos") or []
            if repos:
                return f"{repos[0]}#1"
        if provider == "jira":
            projects = scope.get("projects") or []
            if projects:
                return f"{projects[0]}-1"
    return None


def build_demo_context(settings: Settings, principal: str, cache: PackageCache) -> dict[str, Any]:
    savings_store = get_token_savings_store(settings)
    summary = savings_store.summary(principal)
    last = savings_store.last_for_principal(principal)

    benchmark = _benchmark_comparison()
    comparisons: dict[str, Any] = {"benchmark": benchmark}
    comparison = benchmark
    default_view = "benchmark"

    if last:
        last_cmp = _last_comparison(last)
        comparisons["last"] = last_cmp
        comparison = last_cmp
        default_view = "last"

    total_cmp = _total_comparison(summary)
    if total_cmp:
        comparisons["total"] = total_cmp

    package_insights: Optional[dict[str, Any]] = None
    if last:
        package_id = str(last.get("package_id") or "")
        entry = cache.find(package_id) if package_id else None
        if entry is not None:
            package_insights = {
                "package_id": package_id,
                "title": entry.package.get("entity", {}).get("title"),
                **_package_insights(entry.package),
            }

    indexed_refs = _indexed_refs(settings)
    suggested = _suggested_ref(settings, indexed_refs)
    agents = {
        key: {
            **meta,
            "prompt": meta["slash"].format(ref=suggested or "owner/repo#42"),
        }
        for key, meta in AGENT_PROMPTS.items()
    }

    return {
        "comparison": comparison,
        "comparisons": comparisons,
        "default_view": default_view,
        "indexed_refs": indexed_refs,
        "token_savings": summary,
        "package_insights": package_insights,
        "suggested_ref": suggested,
        "agents": agents,
        "receipt_hint": (
            "Mark context as helpful in the Sidebar or submit a usage receipt — "
            "warm ranking learns what your team actually uses."
        ),
    }
