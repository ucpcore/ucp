"""FastAPI application: versioned REST API + MCP over Streamable HTTP.

Errors follow RFC 9457 (application/problem+json). When UCP_SERVER_API_KEY
is set, every endpoint except the health probes requires a Bearer key,
compared in constant time.
"""
from __future__ import annotations

import json
import os
from typing import Any, Literal, Optional

import ucp
from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from .hosted_view import (
    build_local_setup,
    build_setup_payload,
    display_host_hint,
    render_hosted_landing,
    render_local_landing,
)
from .tenant import TenantPathMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from . import __version__
from .admin_view import render_admin_app
from .cache import PackageCache
from .config import MAX_BODY_BYTES, Settings, load_settings
from .mcp_tools import build_mcp
from .receipt_models import ReceiptRequest
from .receipt_store import get_receipt_store
from .service import GenerationService, InvalidRefError, PermissionError, SourceError

from .errors import problem
from .auth import AuthMiddleware, auth_required
from .token_store import VALID_SCOPES, AuthContext, get_token_store
from .access_audit import get_access_audit_store
from .usage_store import get_usage_store
from .billing_store import get_billing_store
from .oauth import build_oauth_router
from .mcp_oauth import build_mcp_oauth_router
from .invite_store import (
    DEFAULT_SCOPES,
    get_invite_store,
    invite_dashboard_url,
)
from .portal_auth import build_portal_auth_router, get_portal_session, require_portal_session
from .portal_static import resolve_portal_dist
from .user_store import get_user_store


class GenerateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    source: Literal["github", "jira", "confluence", "gdrive", "yandex_disk"]
    ref: str = Field(min_length=1, max_length=512,
                     description="owner/repo#123 (GitHub), PROJ-123 (Jira), SPACE:PAGE_ID (Confluence), file id (Drive), RESOURCE:HASH or path:/… (Yandex)")
    llm: bool = False
    since: Optional[str] = Field(default=None, max_length=64,
                                 description="ISO timestamp: add a context_diff since this moment")
    audience: Optional[str] = Field(default=None, max_length=200,
                                    description="Service key only: explicit principal; personal tokens derive principal from token name")


class CheckoutRequest(BaseModel):
    model_config = {"extra": "forbid"}

    plan: Literal["pro"] = "pro"


class SimulatePaymentRequest(BaseModel):
    model_config = {"extra": "forbid"}

    session_id: str = Field(min_length=8, max_length=128)


class StripeWebhookStub(BaseModel):
    model_config = {"extra": "forbid"}

    type: Literal["checkout.session.completed", "customer.subscription.deleted"]
    session_id: Optional[str] = Field(default=None, max_length=128)


class CreateTokenRequest(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=120)
    scopes: list[Literal["generate", "receipt", "admin:read"]] = Field(min_length=1)


class MeCreateTokenRequest(BaseModel):
    model_config = {"extra": "forbid"}

    name: Optional[str] = Field(default=None, max_length=120,
                                description="Only for bootstrap when no tokens exist yet")
    rotate: bool = False


class CreateInviteRequest(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=120)
    scopes: list[Literal["generate", "receipt", "admin:read"]] = Field(
        default_factory=lambda: list(DEFAULT_SCOPES)
    )
    ttl_hours: int = Field(default=168, ge=1, le=720)


def _require_user_auth(request: Request) -> AuthContext:
    auth: Optional[AuthContext] = getattr(request.state, "auth", None)
    if auth is None:
        raise StarletteHTTPException(401, "authentication required")
    if auth.is_service:
        raise StarletteHTTPException(403, "personal token required — not service API key")
    return auth


def _resolve_me_principal(request: Request, settings: Settings) -> tuple[str, Optional[AuthContext]]:
    """Portal session cookie or personal API token."""
    portal = get_portal_session(request, settings)
    if portal is not None:
        return portal.display_name, None
    auth = _require_user_auth(request)
    return auth.principal, auth


def _me_token_owner(request: Request, settings: Settings) -> tuple[Optional[str], str]:
    """Portal user id (if any) and principal name for legacy token ownership."""
    portal = get_portal_session(request, settings)
    if portal is not None:
        user = get_user_store(settings).get_by_id(portal.user_id)
        if user is None:
            raise StarletteHTTPException(401, "session expired")
        return user.id, user.display_name
    auth = _require_user_auth(request)
    store = get_token_store(settings)
    user_id = store.get_user_id_for_token(auth.token_id)
    return user_id, auth.principal


def _can_issue_tokens(request: Request, settings: Settings) -> tuple[str, Optional[AuthContext]]:
    portal = get_portal_session(request, settings)
    if portal is not None:
        user = get_user_store(settings).get_by_id(portal.user_id)
        if user is None:
            raise StarletteHTTPException(401, "session expired")
        if not settings.allow_self_service_tokens and user.role != "admin":
            raise StarletteHTTPException(
                403,
                "token self-service disabled — set UCP_ALLOW_SELF_SERVICE_TOKENS=1 or contact admin",
            )
        return user.display_name, None
    auth = getattr(request.state, "auth", None)
    if auth is not None and not auth.is_service:
        return auth.principal, auth
    return _resolve_me_principal(request, settings)


class _ExtensionCorsMiddleware(BaseHTTPMiddleware):
    """CORS + Private Network Access for Chrome extension → localhost (Chrome 142+)."""

    _ALLOW_HEADERS = "Authorization, Content-Type"
    _ALLOW_METHODS = "GET, POST, DELETE, OPTIONS"

    @staticmethod
    def _allow_origin(request: Request) -> str:
        origin = request.headers.get("origin", "")
        if origin.startswith("chrome-extension://"):
            return origin
        return "*"

    def _cors_headers(self, request: Request) -> dict[str, str]:
        return {
            "Access-Control-Allow-Origin": self._allow_origin(request),
            "Access-Control-Allow-Methods": self._ALLOW_METHODS,
            "Access-Control-Allow-Headers": self._ALLOW_HEADERS,
            "Access-Control-Allow-Private-Network": "true",
        }

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=self._cors_headers(request))
        response = await call_next(request)
        origin = request.headers.get("origin", "")
        if origin.startswith("chrome-extension://") or request.headers.get(
            "access-control-request-private-network"
        ):
            for key, value in self._cors_headers(request).items():
                response.headers[key] = value
        return response


class _BodyLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Response:
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
            return problem(
                413,
                "Payload Too Large",
                f"Request body exceeds the {MAX_BODY_BYTES} byte limit.",
                "payload-too-large",
            )
        return await call_next(request)


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or load_settings()
    cache = PackageCache(settings.cache_dir, settings.cache_ttl)
    service = GenerationService(settings, cache)
    usage_store = get_usage_store(settings)
    billing_store = get_billing_store(settings)

    # path="/mcp" + mount at "/" (below) => the endpoint is exactly /mcp,
    mcp_app = build_mcp(
        service,
        usage_store=usage_store,
        billing_store=billing_store,
    ).http_app(path="/mcp", stateless_http=True)

    app = FastAPI(
        title="ucp-server",
        version=__version__,
        description=(
            "Self-hosted UCP generation service. Turn GitHub issues and Jira "
            "tickets into Universal Context Packages over REST or MCP "
            "(Streamable HTTP at /mcp). Spec: https://ucpcore.org"
        ),
        lifespan=mcp_app.lifespan,
    )
    app.state.settings = settings
    app.state.cache = cache
    app.state.service = service

    # --- error format: RFC 9457 -------------------------------------------------
    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return problem(exc.status_code, exc.detail or "Error", str(exc.detail), "http-error")

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        return problem(422, "Validation Error", details, "validation-error")

    @app.exception_handler(InvalidRefError)
    async def _invalid_ref(request: Request, exc: InvalidRefError) -> JSONResponse:
        return problem(400, "Invalid Reference", str(exc), "invalid-ref")

    @app.exception_handler(SourceError)
    async def _source_error(request: Request, exc: SourceError) -> JSONResponse:
        message = str(exc)
        if "not found" in message.lower():
            return problem(404, "Upstream Entity Not Found", message, "upstream-not-found")
        return problem(502, "Upstream Error", message, "upstream-error")

    @app.exception_handler(PermissionError)
    async def _permission_error(request: Request, exc: PermissionError) -> JSONResponse:
        message = str(exc)
        if "unavailable" in message.lower() or "not installed" in message.lower():
            return problem(503, "Permissions Unavailable", message, "permissions-unavailable")
        return problem(403, "Forbidden", message, "permission-denied")

    # --- MCP home landing (always; before MCP mount) -----------------------------
    host_hint = display_host_hint(settings.host, settings.port)

    def _setup_payload() -> dict[str, Any]:
        if settings.tenant_slug and settings.public_base_url:
            return build_setup_payload(
                tenant_slug=settings.tenant_slug,
                public_base_url=settings.public_base_url,
                version=__version__,
            )
        return build_local_setup(version=__version__, host_hint=host_hint)

    @app.get("/", tags=["hosted"], response_class=HTMLResponse)
    async def mcp_home() -> HTMLResponse:
        if settings.tenant_slug and settings.public_base_url:
            html = render_hosted_landing(
                tenant_slug=settings.tenant_slug,
                public_base_url=settings.public_base_url,
                version=__version__,
            )
        else:
            html = render_local_landing(version=__version__, host_hint=host_hint)
        return HTMLResponse(html)

    @app.get("/setup", tags=["hosted"])
    async def mcp_setup(
        request: Request,
        format: Optional[str] = Query(default=None, alias="format"),
    ) -> Any:
        payload = _setup_payload()
        accept = request.headers.get("accept", "")
        wants_json = format == "json" or (
            "application/json" in accept and "text/html" not in accept
        )
        if wants_json:
            return payload
        return RedirectResponse("/dashboard/setup", status_code=302)

    # --- health probes (never authenticated) --------------------------------------
    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/readyz", tags=["health"])
    async def readyz() -> dict[str, str]:
        if settings.cache_ttl > 0 and not os.access(settings.cache_dir, os.W_OK):
            raise StarletteHTTPException(503, "cache directory is not writable")
        return {"status": "ready"}

    # --- REST API v1 -----------------------------------------------------------
    @app.post("/v1/generate", tags=["generate"])
    async def generate(body: GenerateRequest, request: Request, response: Response) -> dict[str, Any]:
        auth = getattr(request.state, "auth", None)
        audience = body.audience
        principal = "service"
        if auth is not None and not auth.is_service:
            audience = auth.principal
            principal = auth.principal
        plan = billing_store.get_state().plan
        quota_err = usage_store.check_quota(principal, plan=plan)
        if quota_err and principal != "service":
            raise StarletteHTTPException(429, quota_err)
        entry_id, package, cached = service.generate(
            body.source, body.ref, llm=body.llm, since=body.since, audience=audience
        )
        if not cached and principal != "service":
            usage_store.record_package_generated(principal)
        response.headers["X-UCP-Package-Id"] = entry_id
        response.headers["X-UCP-Cache"] = "hit" if cached else "miss"
        return package

    @app.get("/v1/packages", tags=["packages"])
    async def list_packages() -> list[dict[str, Any]]:
        return [
            {
                "id": entry.id,
                "title": entry.package["entity"]["title"],
                "entity_id": entry.package["entity"]["ref"]["id"],
                "system": entry.package["entity"]["ref"]["system"],
                "generated_at": entry.package["generated_at"],
            }
            for entry in cache.entries()
        ]

    @app.get("/v1/packages/{package_id}", tags=["packages"])
    async def get_package(package_id: str) -> dict[str, Any]:
        entry = cache.find(package_id)
        if entry is None:
            raise StarletteHTTPException(404, f"no cached package with id '{package_id}'")
        return entry.package

    @app.get("/v1/packages/{package_id}/markdown", tags=["packages"])
    async def get_package_markdown(
        package_id: str,
        token_budget: Optional[int] = Query(default=None, ge=1, le=1_000_000),
    ) -> PlainTextResponse:
        entry = cache.find(package_id)
        if entry is None:
            raise StarletteHTTPException(404, f"no cached package with id '{package_id}'")
        pkg = ucp.Package.model_validate(entry.package)
        return PlainTextResponse(
            ucp.render(pkg, token_budget=token_budget), media_type="text/markdown"
        )

    @app.post("/v1/receipt", tags=["receipt"])
    async def submit_receipt(body: ReceiptRequest) -> dict[str, Any]:
        """Usage Receipt: consumer feedback after working with a UCP (RFC-0007)."""
        payload = body.model_dump(mode="json", exclude_none=True)
        try:
            ucp.validate_receipt(payload)
        except ucp.UCPValidationError as exc:
            raise StarletteHTTPException(422, str(exc)) from exc
        entry = cache.find(body.package_id)
        if entry is None:
            raise StarletteHTTPException(
                404,
                f"no cached package with id '{body.package_id}' — generate context first",
            )
        payload = body.model_dump()
        for gap in payload.get("gaps_needed") or []:
            if len(gap) > 500:
                raise StarletteHTTPException(422, "gaps_needed item exceeds 500 characters")
        stored = get_receipt_store(settings).append(payload)
        return {
            "status": "ok",
            "stored_at": stored.stored_at,
            "package_id": body.package_id,
            "outcome": body.outcome,
        }

    @app.get("/v1/admin/receipts", tags=["admin"])
    async def admin_receipts(
        limit: int = Query(default=20, ge=1, le=200),
    ) -> dict[str, Any]:
        store = get_receipt_store(settings)
        return {
            "aggregate": store.analytics(limit=200),
            "receipts": store.list_recent(limit=limit),
        }

    @app.get("/v1/me/receipt-analytics", tags=["me"])
    async def me_receipt_analytics(request: Request) -> dict[str, Any]:
        principal, _ = _resolve_me_principal(request, settings)
        store = get_receipt_store(settings)
        return store.analytics(limit=200, principal=principal)

    @app.post("/v1/webhooks/github", tags=["webhooks"])
    async def github_webhook(request: Request) -> dict[str, Any]:
        if not settings.engine_enabled:
            raise StarletteHTTPException(503, "engine is not enabled")
        if not settings.redis_url:
            raise StarletteHTTPException(503, "REDIS_URL is not configured")
        secret = settings.github_webhook_secret
        if not secret:
            raise StarletteHTTPException(503, "GITHUB_WEBHOOK_SECRET is not configured")
        signature = request.headers.get("X-Hub-Signature-256", "")
        body = await request.body()
        from .webhooks import handle_github_webhook

        try:
            return handle_github_webhook(
                body=body,
                signature=signature,
                secret=secret,
                redis_url=settings.redis_url,
            )
        except PermissionError as exc:
            raise StarletteHTTPException(401, str(exc)) from exc
        except ValueError as exc:
            raise StarletteHTTPException(503, str(exc)) from exc
        except json.JSONDecodeError as exc:
            raise StarletteHTTPException(400, "invalid JSON payload") from exc

    # --- Billing stub (Stripe emulation, RFC-0009) -----------------------------
    @app.get("/v1/billing/plans", tags=["billing"])
    async def billing_plans() -> dict[str, Any]:
        store = get_billing_store(settings)
        return {"plans": store.list_plans(), "stub_mode": True}

    @app.get("/v1/billing/subscription", tags=["billing"])
    async def billing_subscription(request: Request) -> dict[str, Any]:
        state = billing_store.get_state().to_dict()
        auth = getattr(request.state, "auth", None)
        if auth is not None and not auth.is_service:
            usage = usage_store.summary(auth.principal, plan=state["plan"])
            state["packages_used"] = usage["packages_used"]
            state["packages_limit"] = usage["packages_limit"]
            state["principal"] = auth.principal
        return state

    @app.post("/v1/billing/checkout", tags=["billing"])
    async def billing_checkout(body: CheckoutRequest) -> dict[str, Any]:
        store = get_billing_store(settings)
        try:
            return store.create_checkout_session(plan=body.plan)
        except ValueError as exc:
            raise StarletteHTTPException(400, str(exc)) from exc

    @app.post("/v1/billing/portal", tags=["billing"])
    async def billing_portal() -> dict[str, Any]:
        return get_billing_store(settings).create_portal_session()

    @app.post("/v1/billing/simulate-payment", tags=["billing"])
    async def billing_simulate_payment(body: SimulatePaymentRequest) -> dict[str, Any]:
        store = get_billing_store(settings)
        try:
            state = store.complete_checkout(session_id=body.session_id)
        except ValueError as exc:
            raise StarletteHTTPException(400, str(exc)) from exc
        return {"status": "ok", "subscription": state.to_dict(), "stub_mode": True}

    @app.post("/v1/billing/webhook/stripe", tags=["billing"])
    async def billing_stripe_webhook(body: StripeWebhookStub) -> dict[str, Any]:
        store = get_billing_store(settings)
        try:
            return store.simulate_stripe_webhook(
                event_type=body.type,
                session_id=body.session_id,
            )
        except ValueError as exc:
            raise StarletteHTTPException(400, str(exc)) from exc

    @app.get("/v1/admin/sources", tags=["admin"])
    async def admin_sources() -> dict[str, Any]:
        if not settings.engine_enabled or not settings.database_url:
            raise StarletteHTTPException(
                503, "engine is not enabled (set CONTEXTOS_ENGINE_ENABLED and DATABASE_URL)"
            )
        from contextos_engine.admin import build_sources_health
        from contextos_engine.config import load_settings as load_engine_settings

        return build_sources_health(load_engine_settings())

    @app.get("/v1/admin/audit", tags=["admin"])
    async def admin_audit(
        limit: int = Query(default=20, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        if not settings.engine_enabled or not settings.database_url:
            raise StarletteHTTPException(503, "engine is not enabled")
        from contextos_engine.config import load_settings as load_engine_settings
        from contextos_engine.index_store import IndexStore

        store = IndexStore(load_engine_settings())
        entries, total = store.list_audit_entries(limit=limit, offset=offset)
        return {"entries": entries, "total": total, "limit": limit, "offset": offset}

    @app.get("/v1/admin/eval", tags=["admin"])
    async def admin_eval() -> dict[str, Any]:
        from .eval_report import load_eval_report

        return load_eval_report(settings)

    # --- User self-service (portal) --------------------------------------------
    @app.get("/v1/me/bootstrap-available", tags=["me"])
    async def bootstrap_available() -> dict[str, bool]:
        if get_user_store(settings).has_users():
            return {"bootstrap": False}
        store = get_token_store(settings)
        return {"bootstrap": not store.has_active_tokens()}

    @app.get("/v1/me/invites/preview", tags=["me"])
    async def invite_preview(code: str = Query(min_length=8, max_length=128)) -> dict[str, Any]:
        preview = get_invite_store(settings).preview(code.strip())
        if preview is None:
            raise StarletteHTTPException(404, "invite not found")
        return preview

    @app.get("/v1/me/profile", tags=["me"])
    async def me_profile(request: Request) -> dict[str, Any]:
        portal = get_portal_session(request, settings)
        payload = _setup_payload()
        if portal is not None:
            return {
                "principal": portal.display_name,
                "email": portal.email,
                "scopes": ["generate", "receipt"],
                "role": portal.role,
                "auth_provider": portal.auth_provider,
                "mcp_url": payload["mcp_url"],
                "setup_url": "/dashboard/setup",
                "access_url": "/dashboard/access",
            }
        auth = _require_user_auth(request)
        return {
            "principal": auth.principal,
            "scopes": sorted(auth.scopes),
            "mcp_url": payload["mcp_url"],
            "setup_url": "/dashboard/setup",
            "access_url": "/dashboard/access",
        }

    @app.get("/v1/me/usage", tags=["me"])
    async def me_usage(request: Request) -> dict[str, Any]:
        principal, _ = _resolve_me_principal(request, settings)
        plan = billing_store.get_state().plan
        summary = usage_store.summary(principal, plan=plan)
        audit = get_access_audit_store(settings)
        stats = audit.principal_stats(principal, days=365)
        receipts = get_receipt_store(settings).list_recent(limit=200)
        mine = [
            r for r in receipts
            if (r.get("receipt") or {}).get("principal") == principal
        ]
        outcomes: dict[str, int] = {}
        for row in mine:
            outcome = (row.get("receipt") or {}).get("outcome") or "unknown"
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
        recent = audit.list_recent(limit=30, principal=principal)
        return {
            **summary,
            "daily": stats["daily"],
            "by_channel": stats["by_channel"],
            "generates_logged": stats["generates"],
            "recent_activity": recent,
            "receipts": {"total": len(mine), "outcomes": outcomes},
        }

    @app.get("/v1/me/tokens", tags=["me"])
    async def me_list_tokens(request: Request) -> dict[str, Any]:
        user_id, principal = _me_token_owner(request, settings)
        store = get_token_store(settings)
        return {"tokens": store.list_for_user(user_id, principal)}

    @app.post("/v1/me/tokens", tags=["me"])
    async def me_create_token(request: Request, body: MeCreateTokenRequest) -> dict[str, Any]:
        store = get_token_store(settings)
        auth: Optional[AuthContext] = getattr(request.state, "auth", None)
        portal = get_portal_session(request, settings)
        owner_user_id: Optional[str] = None
        client_label = "Dashboard"
        auth_method = "manual"

        if portal is not None:
            user = get_user_store(settings).get_by_id(portal.user_id)
            if user is None:
                raise StarletteHTTPException(401, "session expired")
            if not settings.allow_self_service_tokens and user.role != "admin":
                raise StarletteHTTPException(
                    403,
                    "token self-service disabled — set UCP_ALLOW_SELF_SERVICE_TOKENS=1",
                )
            principal = user.display_name
            owner_user_id = user.id
            if body.rotate:
                store.revoke_all_for_user(owner_user_id, principal)
        elif auth is None:
            if get_user_store(settings).has_users() or store.has_active_tokens():
                raise StarletteHTTPException(401, "login required — use /dashboard/login")
            principal = (body.name or "").strip()
            if not principal:
                raise StarletteHTTPException(400, "name is required for the first token")
            client_label = "Bootstrap"
        elif auth.is_service:
            raise StarletteHTTPException(
                403,
                "use POST /v1/admin/tokens with service key for team provisioning",
            )
        else:
            principal = auth.principal
            owner_user_id = store.get_user_id_for_token(auth.token_id)
            if body.rotate:
                store.revoke_all_for_user(owner_user_id, principal)

        try:
            token, raw = store.create(
                name=principal,
                scopes=["generate", "receipt"],
                user_id=owner_user_id,
                client_label=client_label,
                auth_method=auth_method,
            )
        except ValueError as exc:
            raise StarletteHTTPException(400, str(exc)) from exc
        return {
            "token": token.to_public(),
            "secret": raw,
            "message": "Сохраните secret сейчас — показывается один раз.",
        }

    @app.delete("/v1/me/tokens/{token_id}", tags=["me"])
    async def me_revoke_token(request: Request, token_id: str) -> dict[str, str]:
        user_id, principal = _me_token_owner(request, settings)
        store = get_token_store(settings)
        if not store.revoke_for_user(token_id, user_id, principal):
            raise StarletteHTTPException(404, f"no active token with id '{token_id}'")
        return {"status": "revoked", "id": token_id}

    @app.get("/v1/admin/tokens", tags=["admin"])
    async def admin_list_tokens() -> dict[str, Any]:
        store = get_token_store(settings)
        return {"tokens": store.list_tokens(), "valid_scopes": sorted(VALID_SCOPES)}

    @app.post("/v1/admin/tokens", tags=["admin"])
    async def admin_create_token(body: CreateTokenRequest) -> dict[str, Any]:
        store = get_token_store(settings)
        try:
            token, raw = store.create(name=body.name, scopes=list(body.scopes))
        except ValueError as exc:
            raise StarletteHTTPException(400, str(exc)) from exc
        return {
            "token": token.to_public(),
            "secret": raw,
            "message": "Store the secret now — it is shown only once.",
        }

    @app.delete("/v1/admin/tokens/{token_id}", tags=["admin"])
    async def admin_revoke_token(token_id: str) -> dict[str, str]:
        store = get_token_store(settings)
        if not store.revoke(token_id):
            raise StarletteHTTPException(404, f"no active token with id '{token_id}'")
        return {"status": "revoked", "id": token_id}

    @app.get("/v1/admin/invites", tags=["admin"])
    async def admin_list_invites() -> dict[str, Any]:
        return {"invites": get_invite_store(settings).list_invites()}

    @app.post("/v1/admin/invites", tags=["admin"])
    async def admin_create_invite(body: CreateInviteRequest) -> dict[str, Any]:
        invite_store = get_invite_store(settings)
        try:
            invite, code = invite_store.create(
                principal_name=body.name,
                scopes=list(body.scopes),
                ttl_hours=body.ttl_hours,
            )
        except ValueError as exc:
            raise StarletteHTTPException(400, str(exc)) from exc
        return {
            "invite": invite.to_public(),
            "code": code,
            "invite_path": f"/dashboard/invite?code={code}",
            "invite_url": invite_dashboard_url(settings, code),
            "message": "Share this link once. Single use.",
        }

    @app.delete("/v1/admin/invites/{invite_id}", tags=["admin"])
    async def admin_revoke_invite(invite_id: str) -> dict[str, str]:
        if not get_invite_store(settings).revoke(invite_id):
            raise StarletteHTTPException(404, f"no pending invite with id '{invite_id}'")
        return {"status": "revoked", "id": invite_id}

    @app.get("/v1/admin/access-log", tags=["admin"])
    async def admin_access_log(
        limit: int = Query(default=20, ge=1, le=200),
    ) -> dict[str, Any]:
        entries = get_access_audit_store(settings).list_recent(limit=limit)
        return {"entries": entries, "limit": limit}

    @app.post("/v1/admin/sync/{source}", tags=["admin"])
    async def admin_sync_source(source: str) -> dict[str, str]:
        if not settings.engine_enabled:
            raise StarletteHTTPException(503, "engine is not enabled")
        redis_url = settings.redis_url
        if not redis_url:
            raise StarletteHTTPException(
                503, "REDIS_URL is not configured (required for sync trigger)"
            )
        from contextos_engine.admin import SyncTriggerError, trigger_source_sync

        try:
            task_id = trigger_source_sync(source, redis_url=redis_url)
        except SyncTriggerError as exc:
            raise StarletteHTTPException(400, str(exc)) from exc
        return {"source": source, "task_id": task_id, "status": "queued"}

    @app.get("/admin", tags=["admin"], response_class=HTMLResponse)
    async def admin_dashboard() -> HTMLResponse:
        """Browser UI: login shell is public; data loads via authenticated fetch."""
        return HTMLResponse(render_admin_app())

    # --- Portal SPA (shadcn dashboard UI) -----------------------------------------
    portal_dist = resolve_portal_dist()
    if portal_dist is not None:

        @app.get("/dashboard", tags=["portal"])
        async def portal_root() -> FileResponse:
            return FileResponse(portal_dist / "index.html")

        @app.get("/dashboard/{asset_path:path}", tags=["portal"])
        async def portal_assets(asset_path: str) -> FileResponse:
            target = portal_dist / asset_path
            if target.is_file():
                return FileResponse(target)
            return FileResponse(portal_dist / "index.html")

        @app.get("/billing", tags=["portal"])
        async def billing_legacy_root() -> RedirectResponse:
            return RedirectResponse("/dashboard", status_code=301)

        @app.get("/billing/{asset_path:path}", tags=["portal"])
        async def billing_legacy_assets(asset_path: str) -> RedirectResponse:
            return RedirectResponse(f"/dashboard/{asset_path}", status_code=301)

    app.include_router(build_portal_auth_router(settings))
    app.include_router(build_oauth_router(settings))
    app.include_router(build_mcp_oauth_router(settings))

    # --- MCP over Streamable HTTP at /mcp ----------------------------------------
    # Mounted at the root as the last route: FastAPI routes above win, and the
    # MCP endpoint is served at exactly /mcp (no 307 redirect).
    app.mount("/", mcp_app)

    # Middleware wraps everything above, including the MCP mount.
    # CORS must be outermost so 401/403 short-circuits from auth still get ACAO headers.
    token_store = get_token_store(settings)
    hosted = bool(settings.tenant_slug) and (
        settings.hosted_mode or bool(settings.public_base_url)
    )
    app.add_middleware(_BodyLimitMiddleware)
    if auth_required(settings, token_store):
        app.add_middleware(AuthMiddleware, settings=settings, token_store=token_store)
    if settings.tenant_slug:
        app.add_middleware(
            TenantPathMiddleware,
            tenant_slug=settings.tenant_slug,
            hosted_mode=hosted,
        )
    app.add_middleware(_ExtensionCorsMiddleware)

    return app
