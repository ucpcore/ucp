"""Portal-facing connector definitions, scope storage, and status."""
from __future__ import annotations

import json
from typing import Any, Optional

from .config import Settings
from .oauth import get_connector_token, oauth_status
from .platform_db import ConnectorCredentialRow, get_session_factory, postgres_available, utcnow

CONNECTOR_SPECS: dict[str, dict[str, Any]] = {
    "github": {
        "label": "GitHub",
        "description": "Issues and pull requests from selected repositories.",
        "oauth_provider": "github",
        "scope_fields": [
            {
                "key": "repos",
                "label": "Repositories",
                "placeholder": "owner/repo, org/other-repo",
                "hint": "Comma-separated full names (owner/repo).",
            }
        ],
    },
    "jira": {
        "label": "Jira",
        "description": "Tickets from selected project keys (Atlassian OAuth).",
        "oauth_provider": "jira",
        "scope_fields": [
            {
                "key": "projects",
                "label": "Project keys",
                "placeholder": "PROJ, DEV",
                "hint": "Comma-separated Jira project keys.",
            },
            {
                "key": "spaces",
                "label": "Confluence spaces",
                "placeholder": "DOCS, RFC",
                "hint": "Optional — same Atlassian login indexes Confluence pages.",
            },
        ],
    },
    "gdrive": {
        "label": "Google Drive",
        "description": "Documents from shared folders (token via env for now).",
        "oauth_provider": None,
        "scope_fields": [
            {
                "key": "folder_ids",
                "label": "Folder IDs",
                "placeholder": "folderId1, folderId2",
                "hint": "Drive folder IDs to index. Requires GOOGLE_DRIVE_ACCESS_TOKEN or service account in env.",
            }
        ],
    },
    "yandex_disk": {
        "label": "Yandex Disk",
        "description": "Files under selected paths (token via env for now).",
        "oauth_provider": None,
        "scope_fields": [
            {
                "key": "paths",
                "label": "Disk paths",
                "placeholder": "/, /Projects",
                "hint": "Root-relative paths. Requires YANDEX_DISK_TOKEN in env.",
            }
        ],
    },
}

_SCOPE_LIST_KEYS = frozenset({"repos", "projects", "spaces", "folder_ids", "paths"})


def _parse_scope_lists(raw: dict[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key, value in raw.items():
        if key not in _SCOPE_LIST_KEYS:
            continue
        if isinstance(value, list):
            items = [str(v).strip() for v in value if str(v).strip()]
        elif isinstance(value, str):
            items = [part.strip() for part in value.split(",") if part.strip()]
        else:
            continue
        if key == "projects":
            items = [p.upper() for p in items]
        if items:
            out[key] = items
    return out


def _load_row(
    session, provider: str, *, tenant_id: Optional[str] = None
) -> Optional[ConnectorCredentialRow]:
    q = session.query(ConnectorCredentialRow).filter_by(provider=provider)
    if tenant_id is not None:
        q = q.filter_by(tenant_id=tenant_id)
    else:
        q = q.filter(ConnectorCredentialRow.tenant_id.is_(None))
    return q.one_or_none()


def get_scope(
    settings: Settings, provider: str, *, tenant_id: Optional[str] = None
) -> dict[str, list[str]]:
    if not postgres_available(settings.database_url):
        return {}
    Session = get_session_factory(settings.database_url)
    with Session() as session:
        row = _load_row(session, provider, tenant_id=tenant_id)
        meta = _read_metadata(row)
        return _parse_scope_lists(meta.get("scope") or {})


def update_scope(
    settings: Settings,
    provider: str,
    scope: dict[str, Any],
    *,
    tenant_id: Optional[str] = None,
) -> dict[str, list[str]]:
    if provider not in CONNECTOR_SPECS:
        raise ValueError(f"unknown connector: {provider}")
    if not postgres_available(settings.database_url):
        raise RuntimeError("DATABASE_URL is required for connector scope")
    parsed = _parse_scope_lists(scope)
    Session = get_session_factory(settings.database_url)
    with Session() as session:
        row = _load_row(session, provider, tenant_id=tenant_id)
        if row is None:
            row = ConnectorCredentialRow(
                tenant_id=tenant_id,
                provider=provider,
                access_token="",
                metadata_json=json.dumps({"scope": parsed}),
                updated_at=utcnow(),
            )
            session.add(row)
        else:
            meta = _read_metadata(row)
            meta["scope"] = parsed
            row.metadata_json = json.dumps(meta)
            row.updated_at = utcnow()
        session.commit()
    if parsed:
        try:
            from .indexing_status import trigger_provider_sync

            trigger_provider_sync(settings, provider)
        except Exception:
            pass
    return parsed


def _oauth_available(settings: Settings, spec: dict[str, Any]) -> bool:
    oauth_provider = spec.get("oauth_provider")
    if oauth_provider == "github":
        return bool(settings.github_oauth_client_id)
    if oauth_provider == "jira":
        return bool(settings.atlassian_oauth_client_id)
    return False


def _connected(
    settings: Settings, provider: str, spec: dict[str, Any], *, tenant_id: Optional[str] = None
) -> tuple[bool, str]:
    oauth_provider = spec.get("oauth_provider") or provider
    token = get_connector_token(settings, oauth_provider, tenant_id=tenant_id)
    if token:
        if postgres_available(settings.database_url):
            Session = get_session_factory(settings.database_url)
            with Session() as session:
                row = _load_row(session, oauth_provider, tenant_id=tenant_id)
                if row and row.access_token:
                    return True, "oauth"
        return True, "env"
    scope = get_scope(settings, provider, tenant_id=tenant_id)
    if scope:
        return False, "scope_only"
    return False, "none"


def list_connectors(
    settings: Settings, *, tenant_id: Optional[str] = None
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for provider, spec in CONNECTOR_SPECS.items():
        connected, source = _connected(settings, provider, spec, tenant_id=tenant_id)
        scope = get_scope(settings, provider, tenant_id=tenant_id)
        oauth_provider = spec.get("oauth_provider")
        connect_url = (
            f"/v1/oauth/{oauth_provider}/start?return_to=/dashboard/integrations"
            if oauth_provider and _oauth_available(settings, spec)
            else None
        )
        items.append(
            {
                "provider": provider,
                "label": spec["label"],
                "description": spec["description"],
                "connected": connected,
                "connection_source": source,
                "oauth_available": _oauth_available(settings, spec),
                "connect_url": connect_url,
                "scope": scope,
                "scope_fields": spec["scope_fields"],
                "scope_configured": bool(scope),
            }
        )
    return {"connectors": items}
