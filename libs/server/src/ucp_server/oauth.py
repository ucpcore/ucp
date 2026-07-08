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
) -> None:
    Session = get_session_factory(settings.database_url)
    expires_at = (
        utcnow() + timedelta(seconds=int(expires_in))
        if expires_in
        else None
    )
    with Session() as session:
        row = (
            session.query(ConnectorCredentialRow)
            .filter_by(provider=provider)
            .one_or_none()
        )
        if row is None:
            row = ConnectorCredentialRow(
                provider=provider,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                metadata_json=json.dumps(metadata or {}),
                updated_at=utcnow(),
            )
            session.add(row)
        else:
            row.access_token = access_token
            row.refresh_token = refresh_token or row.refresh_token
            row.expires_at = expires_at or row.expires_at
            row.metadata_json = json.dumps(metadata or {})
            row.updated_at = utcnow()
        session.commit()


def get_connector_token(settings: Settings, provider: str) -> Optional[str]:
    if provider == "github" and settings.github_token:
        return settings.github_token
    if provider == "jira" and settings.jira_api_token:
        return settings.jira_api_token
    if not postgres_available(settings.database_url):
        return None
    Session = get_session_factory(settings.database_url)
    with Session() as session:
        row = (
            session.query(ConnectorCredentialRow)
            .filter_by(provider=provider)
            .one_or_none()
        )
        if row is None:
            return None
        if row.expires_at and row.expires_at <= utcnow():
            return None
        return row.access_token


def oauth_status(settings: Settings) -> dict[str, Any]:
    providers: dict[str, Any] = {}
    if settings.github_token:
        providers["github"] = {"connected": True, "source": "env"}
    if settings.jira_api_token:
        providers["jira"] = {"connected": True, "source": "env"}
    if postgres_available(settings.database_url):
        Session = get_session_factory(settings.database_url)
        with Session() as session:
            for row in session.query(ConnectorCredentialRow).all():
                providers[row.provider] = {
                    "connected": True,
                    "source": "oauth",
                    "updated_at": row.updated_at.isoformat().replace("+00:00", "Z"),
                }
    return {"providers": providers}


def build_oauth_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/v1/oauth", tags=["oauth"])
    base = (settings.public_base_url or f"http://{settings.host}:{settings.port}").rstrip("/")

    @router.get("/status")
    async def status() -> dict[str, Any]:
        return oauth_status(settings)

    @router.get("/github/start")
    async def github_start(request: Request) -> RedirectResponse:
        _require_pg(settings)
        client_id = getattr(settings, "github_oauth_client_id", None)
        if not client_id:
            raise HTTPException(503, "Set GITHUB_OAUTH_CLIENT_ID")
        state = secrets.token_urlsafe(16)
        _OAUTH_STATE[state] = {"provider": "github"}
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
        _OAUTH_STATE.pop(state, None)
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
        _save_credential(settings, provider="github", access_token=token)
        return RedirectResponse("/admin?oauth=github_ok")

    @router.get("/jira/start")
    async def jira_start() -> RedirectResponse:
        _require_pg(settings)
        client_id = settings.atlassian_oauth_client_id
        if not client_id:
            raise HTTPException(503, "Set ATLASSIAN_OAUTH_CLIENT_ID")
        state = secrets.token_urlsafe(16)
        _OAUTH_STATE[state] = {"provider": "jira"}
        redirect_uri = f"{base}/v1/oauth/jira/callback"
        params = urlencode(
            {
                "audience": "api.atlassian.com",
                "client_id": client_id,
                "scope": "read:jira-work read:jira-user offline_access",
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
        _OAUTH_STATE.pop(state, None)
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
        _save_credential(
            settings,
            provider="jira",
            access_token=token,
            refresh_token=data.get("refresh_token"),
            expires_in=data.get("expires_in"),
        )
        return RedirectResponse("/admin?oauth=jira_ok")

    return router
