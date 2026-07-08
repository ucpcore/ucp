"""Portal authentication — local login, bootstrap, invite signup, SSO stubs."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response

from .config import Settings
from .invite_store import INVITE_PREFIX, get_invite_store
from .portal_session import (
    PortalSession,
    clear_session_cookie,
    read_session_cookie,
    set_session_cookie,
)
from .user_store import get_user_store


class BootstrapRequest(BaseModel):
    model_config = {"extra": "forbid"}

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=256)
    display_name: Optional[str] = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    model_config = {"extra": "forbid"}

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class RegisterInviteRequest(BaseModel):
    model_config = {"extra": "forbid"}

    code: str = Field(min_length=8, max_length=128)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=256)
    display_name: Optional[str] = Field(default=None, max_length=120)


def get_portal_session(request: Request, settings: Settings) -> Optional[PortalSession]:
    cached = getattr(request.state, "portal_session", None)
    if cached is not None:
        return cached
    session = read_session_cookie(request, settings)
    if session is not None:
        request.state.portal_session = session
    return session


def require_portal_session(request: Request, settings: Settings) -> PortalSession:
    session = get_portal_session(request, settings)
    if session is None:
        raise StarletteHTTPException(401, "portal login required")
    return session


def build_portal_auth_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/v1/auth", tags=["auth"])

    @router.get("/bootstrap-available")
    async def bootstrap_available() -> dict[str, bool]:
        return {"bootstrap": not get_user_store(settings).has_users()}

    @router.post("/bootstrap")
    async def bootstrap(body: BootstrapRequest) -> JSONResponse:
        users = get_user_store(settings)
        try:
            user = users.bootstrap_admin(
                email=body.email,
                password=body.password,
                display_name=(body.display_name or body.email.split("@")[0]),
            )
        except ValueError as exc:
            raise StarletteHTTPException(400, str(exc)) from exc
        response = JSONResponse({"user": user.to_public(), "message": "Admin account created"})
        set_session_cookie(response, PortalSession.from_user(user), settings)
        return response

    @router.post("/login")
    async def login(body: LoginRequest) -> JSONResponse:
        user = get_user_store(settings).authenticate_local(email=body.email, password=body.password)
        if user is None:
            raise StarletteHTTPException(401, "invalid email or password")
        response = JSONResponse({"user": user.to_public()})
        set_session_cookie(response, PortalSession.from_user(user), settings)
        return response

    @router.post("/logout")
    async def logout() -> Response:
        response = JSONResponse({"status": "logged_out"})
        clear_session_cookie(response)
        return response

    @router.get("/me")
    async def auth_me(request: Request) -> dict[str, Any]:
        session = get_portal_session(request, settings)
        if session is None:
            raise StarletteHTTPException(401, "not authenticated")
        user = get_user_store(settings).get_by_id(session.user_id)
        if user is None:
            raise StarletteHTTPException(401, "session expired")
        return {
            "user": user.to_public(),
            "allow_self_service_tokens": settings.allow_self_service_tokens,
        }

    @router.post("/register-invite")
    async def register_invite(body: RegisterInviteRequest) -> JSONResponse:
        if not body.code.startswith(INVITE_PREFIX):
            raise StarletteHTTPException(400, "invalid invite code")
        invite_store = get_invite_store(settings)
        preview = invite_store.preview(body.code.strip())
        if preview is None or preview.get("status") != "pending":
            raise StarletteHTTPException(400, "invite is invalid, expired, or already used")
        users = get_user_store(settings)
        display = body.display_name or preview.get("principal_name") or body.email.split("@")[0]
        try:
            user = users.create_local_user(
                email=body.email,
                password=body.password,
                display_name=str(display),
                role="member",
            )
            invite_store.mark_redeemed_by_user(body.code.strip(), user.id)
        except ValueError as exc:
            raise StarletteHTTPException(400, str(exc)) from exc
        response = JSONResponse({"user": user.to_public(), "message": "Account created"})
        set_session_cookie(response, PortalSession.from_user(user), settings)
        return response

    # --- SSO extension points (enterprise) ------------------------------------
    @router.get("/oidc/providers")
    async def oidc_providers() -> dict[str, Any]:
        configured = bool(settings.oidc_issuer and settings.oidc_client_id)
        providers = []
        if configured:
            providers.append(
                {
                    "id": "default",
                    "label": settings.oidc_issuer,
                    "start_url": "/v1/auth/oidc/default/start",
                }
            )
        return {"providers": providers, "configured": configured}

    @router.get("/oidc/{provider_id}/start")
    async def oidc_start(provider_id: str, request: Request) -> Response:
        if not (settings.oidc_issuer and settings.oidc_client_id):
            raise StarletteHTTPException(
                501,
                "OIDC not configured — set UCP_OIDC_ISSUER and UCP_OIDC_CLIENT_ID",
            )
        if provider_id != "default":
            raise StarletteHTTPException(404, f"unknown OIDC provider '{provider_id}'")
        # Placeholder: real implementation will redirect to IdP authorization URL.
        raise StarletteHTTPException(
            501,
            "OIDC authorization redirect not implemented yet — use local login or invite",
        )

    @router.get("/oidc/{provider_id}/callback")
    async def oidc_callback(provider_id: str, code: Optional[str] = Query(default=None)) -> Response:
        if not code:
            raise StarletteHTTPException(400, "missing authorization code")
        raise StarletteHTTPException(
            501,
            "OIDC callback handler not implemented yet — upsert_oidc_user() is ready on the backend",
        )

    return router
