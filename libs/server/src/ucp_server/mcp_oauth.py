"""MCP OAuth 2.1 (RFC 9728 + PKCE) — Cursor Authenticate flow for Streamable HTTP /mcp."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from .config import Settings
from .mcp_oauth_view import render_mcp_consent_cancelled, render_mcp_consent_page
from .portal_auth import get_portal_session
from .token_store import get_token_store
from .user_store import get_user_store

MCP_SCOPES = ("generate", "receipt")
_CODE_TTL_SEC = 600
_CONSENT_TTL_SEC = 600
_CLIENT_TTL_SEC = 86400 * 365


def public_base(settings: Settings) -> str:
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    host = settings.host.strip() or "127.0.0.1"
    if host in {"0.0.0.0", "::", "[::]"}:
        host = "127.0.0.1"
    return f"http://{host}:{settings.port}"


def mcp_resource_url(settings: Settings) -> str:
    base = public_base(settings)
    if settings.tenant_slug:
        return f"{base}/v1/{settings.tenant_slug}/mcp"
    return f"{base}/mcp"


def mcp_oauth_issuer(settings: Settings) -> str:
    return f"{public_base(settings)}/v1/oauth/mcp"


def resource_metadata_url(settings: Settings) -> str:
    resource = mcp_resource_url(settings)
    base = public_base(settings)
    if settings.tenant_slug:
        return f"{base}/.well-known/oauth-protected-resource/v1/{settings.tenant_slug}/mcp"
    return f"{base}/.well-known/oauth-protected-resource"


def authorization_server_metadata_url(settings: Settings) -> str:
    issuer = mcp_oauth_issuer(settings)
    base = public_base(settings)
    return f"{base}/.well-known/oauth-authorization-server/v1/oauth/mcp"


def protected_resource_metadata(settings: Settings) -> dict[str, Any]:
    return {
        "resource": mcp_resource_url(settings),
        "authorization_servers": [mcp_oauth_issuer(settings)],
        "scopes_supported": list(MCP_SCOPES),
        "bearer_methods_supported": ["header"],
    }


def authorization_server_metadata(settings: Settings) -> dict[str, Any]:
    issuer = mcp_oauth_issuer(settings)
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/token",
        "registration_endpoint": f"{issuer}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": list(MCP_SCOPES),
    }


def mcp_unauthorized_response(settings: Settings) -> JSONResponse:
    meta_url = resource_metadata_url(settings)
    scope = " ".join(MCP_SCOPES)
    return JSONResponse(
        status_code=401,
        content={
            "type": "about:blank",
            "title": "Unauthorized",
            "status": 401,
            "detail": "MCP authentication required — use OAuth (Authenticate in Cursor) or Bearer ctx_ token.",
        },
        media_type="application/problem+json",
        headers={
            "WWW-Authenticate": (
                f'Bearer resource_metadata="{meta_url}", scope="{scope}"'
            ),
        },
    )


@dataclass
class _OAuthClient:
    client_id: str
    client_name: str
    redirect_uris: list[str]
    created_at: float


@dataclass
class _PendingConsent:
    consent_id: str
    client_id: str
    redirect_uri: str
    code_challenge: str
    code_challenge_method: str
    state: Optional[str]
    user_id: str
    expires_at: float


@dataclass
class _AuthCode:
    code: str
    client_id: str
    user_id: str
    principal: str
    redirect_uri: str
    code_challenge: str
    code_challenge_method: str
    expires_at: float


class _McpOAuthStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.is_file():
            self._write({"clients": {}, "codes": {}, "consents": {}})

    def _read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def register_client(
        self,
        *,
        client_name: str,
        redirect_uris: list[str],
    ) -> _OAuthClient:
        if not redirect_uris:
            raise ValueError("redirect_uris required")
        client_id = secrets.token_urlsafe(16)
        client = _OAuthClient(
            client_id=client_id,
            client_name=client_name or "MCP Client",
            redirect_uris=redirect_uris,
            created_at=time.time(),
        )
        data = self._read()
        data["clients"][client_id] = {
            "client_name": client.client_name,
            "redirect_uris": client.redirect_uris,
            "created_at": client.created_at,
        }
        self._write(data)
        return client

    def get_client(self, client_id: str) -> Optional[_OAuthClient]:
        row = self._read()["clients"].get(client_id)
        if not row:
            return None
        return _OAuthClient(
            client_id=client_id,
            client_name=row["client_name"],
            redirect_uris=list(row["redirect_uris"]),
            created_at=float(row["created_at"]),
        )

    def save_consent(self, entry: _PendingConsent) -> None:
        data = self._read()
        data.setdefault("consents", {})
        data["consents"][entry.consent_id] = {
            "client_id": entry.client_id,
            "redirect_uri": entry.redirect_uri,
            "code_challenge": entry.code_challenge,
            "code_challenge_method": entry.code_challenge_method,
            "state": entry.state,
            "user_id": entry.user_id,
            "expires_at": entry.expires_at,
        }
        self._write(data)

    def pop_consent(self, consent_id: str) -> Optional[_PendingConsent]:
        data = self._read()
        consents = data.setdefault("consents", {})
        row = consents.pop(consent_id, None)
        if not row:
            return None
        self._write(data)
        if float(row["expires_at"]) < time.time():
            return None
        return _PendingConsent(
            consent_id=consent_id,
            client_id=row["client_id"],
            redirect_uri=row["redirect_uri"],
            code_challenge=row["code_challenge"],
            code_challenge_method=row["code_challenge_method"],
            state=row.get("state"),
            user_id=row["user_id"],
            expires_at=float(row["expires_at"]),
        )

    def save_code(self, entry: _AuthCode) -> None:
        data = self._read()
        data["codes"][entry.code] = {
            "client_id": entry.client_id,
            "user_id": entry.user_id,
            "principal": entry.principal,
            "redirect_uri": entry.redirect_uri,
            "code_challenge": entry.code_challenge,
            "code_challenge_method": entry.code_challenge_method,
            "expires_at": entry.expires_at,
        }
        self._write(data)

    def pop_code(self, code: str) -> Optional[_AuthCode]:
        data = self._read()
        row = data["codes"].pop(code, None)
        if not row:
            return None
        self._write(data)
        if float(row["expires_at"]) < time.time():
            return None
        return _AuthCode(
            code=code,
            client_id=row["client_id"],
            user_id=row["user_id"],
            principal=row["principal"],
            redirect_uri=row["redirect_uri"],
            code_challenge=row["code_challenge"],
            code_challenge_method=row["code_challenge_method"],
            expires_at=float(row["expires_at"]),
        )


_store: Optional[_McpOAuthStore] = None


def get_mcp_oauth_store(settings: Settings) -> _McpOAuthStore:
    global _store
    if _store is None:
        _store = _McpOAuthStore(settings.cache_dir / "mcp_oauth" / "clients.json")
    return _store


def _verify_pkce(code_verifier: str, code_challenge: str, method: str) -> bool:
    if method != "S256":
        return False
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    computed = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return hmac.compare_digest(computed, code_challenge)


# OAuth 2.1: after POST /approve the redirect MUST be 302/303 — not 307.
# Browsers preserve POST on 307; MCP clients listen for GET on /callback only.
_OAUTH_REDIRECT_STATUS = 303


def _redirect_with_code(*, redirect_uri: str, code: str, state: Optional[str]) -> RedirectResponse:
    params: dict[str, str] = {"code": code}
    if state:
        params["state"] = state
    separator = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(
        f"{redirect_uri}{separator}{urlencode(params)}",
        status_code=_OAUTH_REDIRECT_STATUS,
    )


def _redirect_denied(*, redirect_uri: str, state: Optional[str]) -> RedirectResponse:
    params: dict[str, str] = {
        "error": "access_denied",
        "error_description": "User denied authorization",
    }
    if state:
        params["state"] = state
    separator = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(
        f"{redirect_uri}{separator}{urlencode(params)}",
        status_code=_OAUTH_REDIRECT_STATUS,
    )


def _validate_authorize_params(
    store: _McpOAuthStore,
    *,
    response_type: str,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
) -> _OAuthClient:
    if response_type != "code":
        raise HTTPException(400, "unsupported response_type")
    if code_challenge_method != "S256":
        raise HTTPException(400, "only S256 PKCE is supported")
    client = store.get_client(client_id)
    if client is None:
        raise HTTPException(400, "unknown client_id")
    if redirect_uri not in client.redirect_uris:
        raise HTTPException(400, "redirect_uri not registered for client")
    return client


class RegisterClientRequest(BaseModel):
    model_config = {"extra": "allow"}

    client_name: Optional[str] = None
    redirect_uris: list[str] = Field(default_factory=list)
    grant_types: list[str] = Field(default_factory=list)
    response_types: list[str] = Field(default_factory=list)
    token_endpoint_auth_method: Optional[str] = None


def build_mcp_oauth_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["mcp-oauth"])

    @router.get("/.well-known/oauth-protected-resource")
    @router.get("/.well-known/oauth-protected-resource/{suffix:path}")
    async def protected_resource_metadata_route(suffix: str = "") -> dict[str, Any]:
        expected_suffix = ""
        if settings.tenant_slug:
            expected_suffix = f"v1/{settings.tenant_slug}/mcp"
        if suffix and suffix.rstrip("/") != expected_suffix.rstrip("/"):
            raise HTTPException(404, "protected resource metadata not found")
        return protected_resource_metadata(settings)

    @router.get("/.well-known/oauth-authorization-server/{suffix:path}")
    async def authorization_server_metadata_route(suffix: str) -> dict[str, Any]:
        if suffix.rstrip("/") != "v1/oauth/mcp":
            raise HTTPException(404, "authorization server metadata not found")
        return authorization_server_metadata(settings)

    issuer_router = APIRouter(prefix="/v1/oauth/mcp", tags=["mcp-oauth"])

    @issuer_router.get("/.well-known/oauth-authorization-server")
    async def issuer_metadata() -> dict[str, Any]:
        return authorization_server_metadata(settings)

    @issuer_router.post("/register")
    async def register_client(body: RegisterClientRequest) -> JSONResponse:
        store = get_mcp_oauth_store(settings)
        try:
            client = store.register_client(
                client_name=body.client_name or "MCP Client",
                redirect_uris=body.redirect_uris,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return JSONResponse(
            {
                "client_id": client.client_id,
                "client_name": client.client_name,
                "redirect_uris": client.redirect_uris,
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "client_id_issued_at": int(client.created_at),
            },
            status_code=201,
        )

    @issuer_router.get("/authorize")
    async def authorize(
        request: Request,
        response_type: str = Query(default="code"),
        client_id: str = Query(min_length=1),
        redirect_uri: str = Query(min_length=1),
        code_challenge: str = Query(min_length=1),
        code_challenge_method: str = Query(default="S256"),
        state: Optional[str] = Query(default=None),
        scope: Optional[str] = Query(default=None),
    ) -> Response:
        store = get_mcp_oauth_store(settings)
        client = _validate_authorize_params(
            store,
            response_type=response_type,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
        )

        session = get_portal_session(request, settings)
        if session is None:
            return_path = request.url.path + "?" + request.url.query
            login_url = f"/dashboard/login?return={quote(return_path, safe='')}"
            return RedirectResponse(login_url, status_code=302)

        user = get_user_store(settings).get_by_id(session.user_id)
        if user is None:
            raise HTTPException(401, "session expired")

        consent_id = secrets.token_urlsafe(24)
        store.save_consent(
            _PendingConsent(
                consent_id=consent_id,
                client_id=client_id,
                redirect_uri=redirect_uri,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                state=state,
                user_id=user.id,
                expires_at=time.time() + _CONSENT_TTL_SEC,
            )
        )

        cancel_qs = urlencode({"consent_id": consent_id})
        html = render_mcp_consent_page(
            client_name=client.client_name,
            redirect_uri=redirect_uri,
            user_email=user.email,
            user_display_name=user.display_name,
            mcp_url=mcp_resource_url(settings),
            scopes=list(MCP_SCOPES),
            consent_id=consent_id,
            approve_url="/v1/oauth/mcp/authorize/approve",
            cancel_url=f"/v1/oauth/mcp/authorize/cancel?{cancel_qs}",
        )
        return HTMLResponse(html)

    @issuer_router.post("/authorize/approve")
    async def authorize_approve(
        request: Request,
        consent_id: str = Form(min_length=8),
    ) -> Response:
        store = get_mcp_oauth_store(settings)
        pending = store.pop_consent(consent_id.strip())
        if pending is None:
            raise HTTPException(400, "consent expired or invalid")

        session = get_portal_session(request, settings)
        if session is None or session.user_id != pending.user_id:
            raise HTTPException(403, "session mismatch — sign in again")

        user = get_user_store(settings).get_by_id(session.user_id)
        if user is None:
            raise HTTPException(401, "session expired")

        client = store.get_client(pending.client_id)
        if client is None:
            raise HTTPException(400, "client no longer registered")

        code = secrets.token_urlsafe(32)
        store.save_code(
            _AuthCode(
                code=code,
                client_id=pending.client_id,
                user_id=user.id,
                principal=user.display_name,
                redirect_uri=pending.redirect_uri,
                code_challenge=pending.code_challenge,
                code_challenge_method=pending.code_challenge_method,
                expires_at=time.time() + _CODE_TTL_SEC,
            )
        )
        return _redirect_with_code(
            redirect_uri=pending.redirect_uri,
            code=code,
            state=pending.state,
        )

    @issuer_router.get("/authorize/cancel")
    async def authorize_cancel(
        request: Request,
        consent_id: str = Query(min_length=8),
    ) -> Response:
        store = get_mcp_oauth_store(settings)
        pending = store.pop_consent(consent_id.strip())
        if pending is None:
            return HTMLResponse(render_mcp_consent_cancelled(client_name="MCP Client"))

        client = store.get_client(pending.client_id)
        client_name = client.client_name if client else "MCP Client"

        accept = request.headers.get("accept", "")
        if "text/html" in accept and "application/json" not in accept:
            return HTMLResponse(render_mcp_consent_cancelled(client_name=client_name))

        return _redirect_denied(redirect_uri=pending.redirect_uri, state=pending.state)

    @issuer_router.post("/token")
    async def token(
        grant_type: str = Form(...),
        code: Optional[str] = Form(default=None),
        redirect_uri: Optional[str] = Form(default=None),
        client_id: Optional[str] = Form(default=None),
        code_verifier: Optional[str] = Form(default=None),
    ) -> dict[str, Any]:
        if grant_type != "authorization_code":
            raise HTTPException(400, "unsupported grant_type")
        if not code or not redirect_uri or not client_id or not code_verifier:
            raise HTTPException(400, "missing token request parameters")

        store = get_mcp_oauth_store(settings)
        client = store.get_client(client_id)
        if client is None:
            raise HTTPException(400, "invalid client")

        auth_code = store.pop_code(code)
        if auth_code is None:
            raise HTTPException(400, "invalid or expired authorization code")
        if auth_code.client_id != client_id:
            raise HTTPException(400, "client_id mismatch")
        if auth_code.redirect_uri != redirect_uri:
            raise HTTPException(400, "redirect_uri mismatch")
        if not _verify_pkce(code_verifier, auth_code.code_challenge, auth_code.code_challenge_method):
            raise HTTPException(400, "invalid PKCE code_verifier")

        token_store = get_token_store(settings)
        if not settings.allow_self_service_tokens:
            user = get_user_store(settings).get_by_id(auth_code.user_id)
            if user is None or user.role != "admin":
                raise HTTPException(403, "token self-service disabled")

        user = get_user_store(settings).get_by_id(auth_code.user_id)
        principal = user.display_name if user else auth_code.principal
        client = store.get_client(auth_code.client_id)
        client_label = (client.client_name if client else "MCP Client").strip() or "MCP Client"
        _, raw = token_store.create(
            name=principal,
            scopes=["generate", "receipt"],
            user_id=auth_code.user_id,
            client_label=client_label,
            auth_method="oauth",
        )
        return {
            "access_token": raw,
            "token_type": "Bearer",
            "expires_in": 86400 * 90,
            "scope": " ".join(MCP_SCOPES),
        }

    router.include_router(issuer_router)
    return router
