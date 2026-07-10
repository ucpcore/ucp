"""Portal-facing indexing progress from engine health + Redis sync state."""
from __future__ import annotations

from typing import Any, Optional

from .config import Settings
from .connector_config import CONNECTOR_SPECS, get_scope

_SOURCE_BY_PROVIDER = {
    "github": "github",
    "jira": "jira",
    "gdrive": "gdrive",
    "yandex_disk": "yandex_disk",
}


def _eta_minutes(status: str, percent: int, sync_interval: int) -> Optional[int]:
    if status != "syncing" or percent >= 100:
        return None
    remaining = max(1, int(((100 - percent) / 100) * sync_interval / 60))
    return remaining


def _scope_message(
    scope: str,
    status: str,
    percent: int,
    indexed: int,
    sync_interval: int,
) -> str:
    if status == "ready":
        if indexed > 0:
            return f"Indexing `{scope}` complete — {indexed} entities ready. Try /ucp with an issue from this scope."
        return f"Indexing `{scope}` complete — first package ready."
    if status == "syncing":
        eta = _eta_minutes(status, percent, sync_interval)
        if eta:
            return f"Indexing `{scope}`… ~{eta} min until sync finishes."
        return f"Indexing `{scope}`…"
    return f"Waiting to index `{scope}` — save scope or trigger sync."


def _scope_rows(
    settings: Settings,
    *,
    source: str,
    scopes: list[str],
    cursors: dict[str, bool],
    indexed_by_scope: dict[str, int],
    sync_interval: int,
    tenant_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    from contextos_engine.sync_progress import list_scope_progress

    redis_rows = {
        row["scope"]: row
        for row in list_scope_progress(settings.redis_url, source, scopes, tenant_id=tenant_id)
    }
    out: list[dict[str, Any]] = []
    for scope in scopes:
        live = redis_rows.get(scope) or {}
        status = str(live.get("status") or "idle")
        percent = int(live.get("percent") or 0)
        if status == "idle" and cursors.get(scope):
            status = "ready"
            percent = 100
        elif status == "idle" and indexed_by_scope.get(scope, 0) > 0:
            status = "ready"
            percent = 100
        out.append(
            {
                "scope": scope,
                "status": status,
                "percent": percent,
                "indexed_entities": indexed_by_scope.get(scope, 0),
                "batch_indexed": int(live.get("indexed") or 0),
                "batch_total": int(live.get("total") or 0),
                "eta_minutes": _eta_minutes(status, percent, sync_interval),
                "message": _scope_message(scope, status, percent, indexed_by_scope.get(scope, 0), sync_interval),
            }
        )
    return out


def _indexed_by_scope(source: str, scopes: list[str], health_sources: list[dict]) -> dict[str, int]:
    block = next((s for s in health_sources if s.get("source") == source), None)
    if block is None:
        return {scope: 0 for scope in scopes}
    total = int(block.get("indexed_entities") or 0)
    if not scopes:
        return {}
    if len(scopes) == 1:
        return {scopes[0]: total}
    per = total // len(scopes)
    return {scope: per for scope in scopes}


def get_indexing_status(
    settings: Settings,
    *,
    tenant_id: Optional[str] = None,
    tenant_slug: Optional[str] = None,
) -> dict[str, Any]:
    if not settings.engine_enabled or not settings.database_url:
        return {"sources": [], "overall_percent": 0, "status": "disabled"}

    from contextos_engine.admin.health import build_sources_health
    from contextos_engine.config import EngineSettings

    graph_group = settings.graph_group_id
    if tenant_id:
        graph_group = f"t{tenant_id}"
    engine_settings = EngineSettings.model_construct(
        engine_enabled=settings.engine_enabled,
        database_url=settings.database_url,
        tenant_slug=tenant_slug or settings.tenant_slug,
        tenant_id=tenant_id,
        neo4j_uri=settings.neo4j_uri,
        neo4j_user=settings.neo4j_user,
        neo4j_password=settings.neo4j_password,
        graph_group_id=graph_group,
        spicedb_enabled=settings.spicedb_enabled,
        github_token=settings.github_token,
        github_repos=[],
        jira_base_url=settings.jira_base_url,
        jira_email=settings.jira_email,
        jira_api_token=settings.jira_api_token,
        jira_projects=[],
        redis_url=settings.redis_url or "redis://127.0.0.1:6379/0",
    )
    health = build_sources_health(engine_settings)
    health_sources = health.get("sources") or []

    sources_out: list[dict[str, Any]] = []
    all_percents: list[int] = []

    for provider, spec in CONNECTOR_SPECS.items():
        source = _SOURCE_BY_PROVIDER.get(provider)
        if source is None:
            continue
        scope_map = get_scope(settings, provider, tenant_id=tenant_id)
        if provider == "jira":
            scopes = scope_map.get("projects") or []
        elif provider == "github":
            scopes = scope_map.get("repos") or []
        elif provider == "gdrive":
            scopes = scope_map.get("folder_ids") or []
        else:
            scopes = scope_map.get("paths") or []

        block = next((s for s in health_sources if s.get("source") == source), None)
        cursor_map = {
            str(row.get("scope")): bool(row.get("has_cursor"))
            for row in (block or {}).get("sync_scopes") or []
        }
        indexed_by_scope = _indexed_by_scope(source, scopes, health_sources)
        sync_interval = int(block.get("sync_interval_seconds") or 900) if block else 900
        scope_rows = _scope_rows(
            settings,
            source=source,
            scopes=scopes,
            cursors=cursor_map,
            indexed_by_scope=indexed_by_scope,
            sync_interval=sync_interval,
            tenant_id=tenant_id,
        )
        if scope_rows:
            overall = round(sum(r["percent"] for r in scope_rows) / len(scope_rows))
        else:
            overall = 100 if block and block.get("status") == "ok" else 0
        status = "idle"
        if any(r["status"] == "syncing" for r in scope_rows):
            status = "syncing"
        elif scope_rows and all(r["status"] == "ready" for r in scope_rows):
            status = "ready"
        elif block and block.get("status") == "ok":
            status = "ready"
            overall = 100
        sources_out.append(
            {
                "provider": provider,
                "source": source,
                "label": spec["label"],
                "overall_percent": overall,
                "status": status,
                "scopes": scope_rows,
            }
        )
        if scopes:
            all_percents.append(overall)

    overall_percent = round(sum(all_percents) / len(all_percents)) if all_percents else 0
    global_status = "idle"
    if any(s["status"] == "syncing" for s in sources_out):
        global_status = "syncing"
    elif sources_out and all(s["status"] == "ready" for s in sources_out if s["scopes"]):
        global_status = "ready"

    return {
        "overall_percent": overall_percent,
        "status": global_status,
        "sources": sources_out,
    }


def trigger_provider_sync(settings: Settings, provider: str) -> Optional[str]:
    source = _SOURCE_BY_PROVIDER.get(provider)
    if source is None or not settings.redis_url or not settings.engine_enabled:
        return None
    from contextos_engine.admin import SyncTriggerError, trigger_source_sync

    try:
        return trigger_source_sync(source, redis_url=settings.redis_url)
    except SyncTriggerError:
        return None
