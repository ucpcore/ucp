"""OAuth 2.0 for GitHub and Jira Cloud connector credentials."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from .config import Settings
from .platform_db import ConnectorCredentialRow, get_session_factory, postgres_available, utcnow

_OAUTH_STATE: dict[str, dict[str, str]] = {}

_DEFAULT_OAUTH_RETURN = "/admin?oauth={provider}_ok"
_ALLOWED_RETURN_PREFIXES = ("/dashboard/", "/admin")


def _safe_return_to(value: Optional[str], *, provider: str) -> str:
    if value and value.startswith(_ALLOWED_RETURN_PREFIXES):
        sep = "&" if "?" in value else "?"
        return f"{value}{sep}connected={provider}"
    return _DEFAULT_OAUTH_RETURN.format(provider=provider)


def _merge_metadata(
    existing: dict[str, Any], incoming: Optional[dict[str, Any]]
) -> dict[str, Any]:
    if not incoming:
        return existing
    merged = {**existing, **incoming}
    if "scope" in existing and "scope" not in incoming:
        merged["scope"] = existing["scope"]
    return merged


async def _atlassian_cloud_metadata(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            "https://api.atlassian.com/oauth/token/accessible-resources",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
    if resp.status_code >= 400:
        return {}
    resources = resp.json()
    if not isinstance(resources, list) or not resources:
        return {}
    site = resources[0]
    url = str(site.get("url") or "").rstrip("/")
    cloud_id = site.get("id")
    meta: dict[str, Any] = {}
    if url:
        meta["jira_base_url"] = url
    if cloud_id:
        meta["cloud_id"] = cloud_id
    return meta


def _require_pg(settings: Settings) -> None:
    if not postgres_available(settings.database_url):
        raise HTTPException(
            503,
            "OAuth requires DATABASE_URL — use deploy/pilot Docker stack with Postgres",
        )


def _save_credential(
    settings: Settings,
    *,
    provider: str,
    access_token: str,
    refresh_token: Optional[str] = None,
    expires_in: Optional[int] = None,
    metadata: Optional[dict[str, Any]] = None,
    tenant_id: Optional[str] = None,
) -> None:
    Session = get_session_factory(settings.database_url)
    expires_at = (
        utcnow() + timedelta(seconds=int(expires_in))
        if expires_in
        else None
    )
    with Session() as session:
        q = session.query(ConnectorCredentialRow).filter_by(provider=provider)
        if tenant_id is not None:
            q = q.filter_by(tenant_id=tenant_id)
        else:
            q = q.filter(ConnectorCredentialRow.tenant_id.is_(None))
        row = q.one_or_none()
        if row is None:
            row = ConnectorCredentialRow(
                tenant_id=tenant_id,
                provider=provider,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                metadata_json=json.dumps(metadata or {}),
                updated_at=utcnow(),
            )
            session.add(row)
        else:
            row.access_token = access_token or row.access_token
            row.refresh_token = refresh_token or row.refresh_token
            row.expires_at = expires_at or row.expires_at
            existing_meta: dict[str, Any] = {}
            if row.metadata_json:
                try:
                    parsed = json.loads(row.metadata_json)
                    if isinstance(parsed, dict):
                        existing_meta = parsed
                except json.JSONDecodeError:
                    existing_meta = {}
            row.metadata_json = json.dumps(_merge_metadata(existing_meta, metadata))
            row.updated_at = utcnow()
        session.commit()


def get_connector_token(
    settings: Settings, provider: str, *, tenant_id: Optional[str] = None
) -> Optional[str]:
    if postgres_available(settings.database_url):
        Session = get_session_factory(settings.database_url)
        with Session() as session:
            q = session.query(ConnectorCredentialRow).filter_by(provider=provider)
            if tenant_id is not None:
                q = q.filter_by(tenant_id=tenant_id)
            else:
                q = q.filter(ConnectorCredentialRow.tenant_id.is_(None))
            row = q.one_or_none()
            if row is not None and row.access_token:
                if row.expires_at and row.expires_at <= utcnow():
                    pass
                else:
                    return row.access_token
    if provider == "github" and settings.github_token:
        return settings.github_token
    if provider == "jira" and settings.jira_api_token:
        return settings.jira_api_token
    return None


def oauth_status(settings: Settings, *, tenant_id: Optional[str] = None) -> dict[str, Any]:
    providers: dict[str, Any] = {}
    if settings.github_token and tenant_id is None:
        providers["github"] = {"connected": True, "source": "env"}
    if settings.jira_api_token and tenant_id is None:
        providers["jira"] = {"connected": True, "source": "env"}
    if postgres_available(settings.database_url):
        Session = get_session_factory(settings.database_url)
        with Session() as session:
            q = session.query(ConnectorCredentialRow)
            if tenant_id is not None:
                q = q.filter_by(tenant_id=tenant_id)
            for row in q.all():
                providers[row.provider] = {
                    "connected": True,
                    "source": "oauth",
                    "updated_at": row.updated_at.isoformat().replace("+00:00", "Z"),
                }
    return {"providers": providers}


from .portal_auth import get_portal_session
from .user_store import get_user_store


def _oauth_tenant_id(request: Request, settings: Settings) -> Optional[str]:
    portal = get_portal_session(request, settings)
    if portal is not None:
        user = get_user_store(settings).get_by_id(portal.user_id)
        if user and user.tenant_id:
            return user.tenant_id
    return getattr(request.state, "tenant_id", None)


def build_oauth_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/v1/oauth", tags=["oauth"])
    base = (settings.public_base_url or f"http://{settings.host}:{settings.port}").rstrip("/")

    @router.get("/status")
    async def status() -> dict[str, Any]:
        return oauth_status(settings)

    @router.get("/github/start")
    async def github_start(
        request: Request,
        return_to: Optional[str] = Query(default=None, max_length=256),
    ) -> RedirectResponse:
        _require_pg(settings)
        client_id = getattr(settings, "github_oauth_client_id", None)
        if not client_id:
            raise HTTPException(503, "Set GITHUB_OAUTH_CLIENT_ID")
        state = secrets.token_urlsafe(16)
        _OAUTH_STATE[state] = {
            "provider": "github",
            "return_to": return_to or "",
            "tenant_id": _oauth_tenant_id(request, settings) or "",
        }
        redirect_uri = f"{base}/v1/oauth/github/callback"
        params = urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": "repo read:user",
                "state": state,
            }
        )
        return RedirectResponse(f"https://github.com/login/oauth/authorize?{params}")

    @router.get("/github/callback")
    async def github_callback(
        code: Optional[str] = None,
        state: Optional[str] = None,
        error: Optional[str] = None,
    ) -> RedirectResponse:
        if error:
            raise HTTPException(400, f"github oauth error: {error}")
        if not code or not state or state not in _OAUTH_STATE:
            raise HTTPException(400, "invalid oauth state")
        oauth_ctx = _OAUTH_STATE.pop(state)
        return_to = oauth_ctx.get("return_to") or None
        tenant_id = oauth_ctx.get("tenant_id") or None
        if tenant_id == "":
            tenant_id = None
        client_id = settings.github_oauth_client_id
        client_secret = settings.github_oauth_client_secret
        if not client_id or not client_secret:
            raise HTTPException(503, "GitHub OAuth not configured")
        redirect_uri = f"{base}/v1/oauth/github/callback"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                json={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
            )
        if resp.status_code >= 400:
            raise HTTPException(502, f"github token exchange failed: {resp.text}")
        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise HTTPException(502, "github returned no access_token")
        _save_credential(settings, provider="github", access_token=token, tenant_id=tenant_id)
        return RedirectResponse(_safe_return_to(return_to, provider="github"))

    @router.get("/jira/start")
    async def jira_start(
        request: Request,
        return_to: Optional[str] = Query(default=None, max_length=256),
    ) -> RedirectResponse:
        _require_pg(settings)
        client_id = settings.atlassian_oauth_client_id
        if not client_id:
            raise HTTPException(503, "Set ATLASSIAN_OAUTH_CLIENT_ID")
        state = secrets.token_urlsafe(16)
        _OAUTH_STATE[state] = {
            "provider": "jira",
            "return_to": return_to or "",
            "tenant_id": _oauth_tenant_id(request, settings) or "",
        }
        redirect_uri = f"{base}/v1/oauth/jira/callback"
        params = urlencode(
            {
                "audience": "api.atlassian.com",
                "client_id": client_id,
                "scope": "read:jira-work read:jira-user read:confluence-space.summary offline_access",
                "redirect_uri": redirect_uri,
                "state": state,
                "response_type": "code",
                "prompt": "consent",
            }
        )
        return RedirectResponse(f"https://auth.atlassian.com/authorize?{params}")

    @router.get("/jira/callback")
    async def jira_callback(
        code: Optional[str] = None,
        state: Optional[str] = None,
        error: Optional[str] = None,
    ) -> RedirectResponse:
        if error:
            raise HTTPException(400, f"jira oauth error: {error}")
        if not code or not state or state not in _OAUTH_STATE:
            raise HTTPException(400, "invalid oauth state")
        oauth_ctx = _OAUTH_STATE.pop(state)
        return_to = oauth_ctx.get("return_to") or None
        tenant_id = oauth_ctx.get("tenant_id") or None
        if tenant_id == "":
            tenant_id = None
        client_id = settings.atlassian_oauth_client_id
        client_secret = settings.atlassian_oauth_client_secret
        if not client_id or not client_secret:
            raise HTTPException(503, "Atlassian OAuth not configured")
        redirect_uri = f"{base}/v1/oauth/jira/callback"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://auth.atlassian.com/oauth/token",
                json={
                    "grant_type": "authorization_code",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
            )
        if resp.status_code >= 400:
            raise HTTPException(502, f"jira token exchange failed: {resp.text}")
        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise HTTPException(502, "atlassian returned no access_token")
        site_meta = await _atlassian_cloud_metadata(token)
        _save_credential(
            settings,
            provider="jira",
            access_token=token,
            refresh_token=data.get("refresh_token"),
            expires_in=data.get("expires_in"),
            metadata=site_meta,
            tenant_id=tenant_id,
        )
        return RedirectResponse(_safe_return_to(return_to, provider="jira"))

    return router
