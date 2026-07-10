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
from .tenant_resolve import build_setup_for_request, resolve_tenant_slug
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
from .webhook_store import VALID_SOURCES, get_webhook_store
from .service import GenerationService, InvalidRefError, PermissionError, SourceError

from .errors import problem
from .auth import AuthMiddleware, auth_required
from .token_store import VALID_SCOPES, AuthContext, get_token_store
from .access_audit import get_access_audit_store
from .usage_store import get_usage_store
from .billing_store import get_billing_store
from .oauth import build_oauth_router
from .connector_config import list_connectors, update_scope, CONNECTOR_SPECS
from .connector_resources import list_connector_resources
from .indexing_status import get_indexing_status
from .demo_context import build_demo_context
from .demo_generate import generate_demo_package
from .demo_rate_limit import DemoRateLimiter
from .mcp_oauth import build_mcp_oauth_router
from .invite_store import (
    DEFAULT_SCOPES,
    get_invite_store,
    invite_dashboard_url,
)
from .portal_auth import build_portal_auth_router, get_portal_session, require_portal_session
from .sidebar_auth import build_sidebar_auth_router, build_sidebar_setup
from .portal_static import resolve_portal_dist
from .user_store import get_user_store
from .tenant_store import bootstrap_tenants, get_tenant_store


class DemoGenerateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    ref: str = Field(
        min_length=3,
        max_length=256,
        description="Public GitHub issue: owner/repo#number",
    )


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


class MeCreateWebhookRequest(BaseModel):
    model_config = {"extra": "forbid"}

    source: Literal["github", "jira", "confluence"]
    label: Optional[str] = Field(default=None, max_length=120)


class MeUpdateConnectorScopeRequest(BaseModel):
    model_config = {"extra": "forbid"}

    scope: dict[str, Any] = Field(default_factory=dict)


def _require_webhook_engine(settings: Settings) -> str:
    if not settings.engine_enabled:
        raise StarletteHTTPException(503, "engine is not enabled")
    redis_url = settings.redis_url
    if not redis_url:
        raise StarletteHTTPException(503, "REDIS_URL is not configured")
    return redis_url


_WEBHOOK_SETUP_HINTS: dict[str, dict[str, Any]] = {
    "github": {
        "provider": "GitHub",
        "events": ["Issues", "Issue comments"],
        "secret_field": "Secret — paste signing_secret from create response",
        "docs": "Settings → Webhooks → Add webhook",
    },
    "jira": {
        "provider": "Jira",
        "events": ["Issue created", "Issue updated", "Comment created"],
        "secret_field": "Optional: header X-Webhook-Secret = signing_secret",
        "docs": "Settings → System → WebHooks → Create webhook",
    },
    "confluence": {
        "provider": "Confluence",
        "events": ["Page created", "Page updated"],
        "secret_field": "Optional: header X-Webhook-Secret = signing_secret",
        "docs": "Space settings → Webhooks (or Confluence automation)",
    },
}


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
    """CORS + Private Network Access for Chrome extension and ucpcore.org/try."""

    _ALLOW_HEADERS = "Authorization, Content-Type"
    _ALLOW_METHODS = "GET, POST, DELETE, OPTIONS"

    @staticmethod
    def _demo_origin_allowed(request: Request) -> Optional[str]:
        if not request.url.path.startswith("/v1/demo/"):
            return None
        settings = getattr(request.app.state, "settings", None)
        if settings is None:
            return None
        origin = request.headers.get("origin", "")
        allowed = {
            o.strip()
            for o in (settings.demo_cors_origins or "").split(",")
            if o.strip()
        }
        if origin in allowed:
            return origin
        return None

    def _cors_headers(self, request: Request, *, force_origin: Optional[str] = None) -> dict[str, str]:
        origin = force_origin or request.headers.get("origin", "")
        if force_origin:
            allow = force_origin
        elif origin.startswith("chrome-extension://"):
            allow = origin
        else:
            allow = "*"
        return {
            "Access-Control-Allow-Origin": allow,
            "Access-Control-Allow-Methods": self._ALLOW_METHODS,
            "Access-Control-Allow-Headers": self._ALLOW_HEADERS,
            "Access-Control-Allow-Private-Network": "true",
        }

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        demo_origin = self._demo_origin_allowed(request)
        if request.method == "OPTIONS" and demo_origin:
            return Response(status_code=204, headers=self._cors_headers(request, force_origin=demo_origin))
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=self._cors_headers(request))
        response = await call_next(request)
        origin = request.headers.get("origin", "")
        if demo_origin:
            for key, value in self._cors_headers(request, force_origin=demo_origin).items():
                response.headers[key] = value
        elif origin.startswith("chrome-extension://") or request.headers.get(
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


class _RoleGateMiddleware(BaseHTTPMiddleware):
    """Hide portal routes on API process and vice versa (split containers)."""

    def __init__(self, app: Any, *, settings: Settings):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        path = request.url.path
        role = self.settings.server_role
        if role == "api" and (
            path.startswith("/dashboard") or path.startswith("/billing")
        ):
            return problem(
                404,
                "Portal Relocated",
                "Portal UI is served on the app host (app.rangor.io).",
                "portal-split",
            )
        if role == "portal" and (
            path.startswith("/v1")
            or path.startswith("/mcp")
            or path == "/admin"
            or path.startswith("/admin/")
        ):
            return problem(
                404,
                "API Relocated",
                "API is served on the api host (api.rangor.io).",
                "api-split",
            )
        return await call_next(request)


def _request_tenant_id(request: Request, settings: Settings) -> Optional[str]:
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        return tenant_id
    if settings.multi_tenant and settings.tenant_slug:
        tenant = get_tenant_store(settings).get_by_slug(settings.tenant_slug)
        return tenant.id if tenant else None
    return None


def _portal_user_tenant_id(request: Request, settings: Settings) -> Optional[str]:
    portal = get_portal_session(request, settings)
    if portal is not None:
        user = get_user_store(settings).get_by_id(portal.user_id)
        if user and user.tenant_id:
            return user.tenant_id
    return _request_tenant_id(request, settings)


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or load_settings()
    bootstrap_tenants(settings)
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
    app.state.demo_rate_limiter = DemoRateLimiter(limit=settings.demo_rate_limit_per_hour)

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

    def _setup_payload(request: Optional[Request] = None) -> dict[str, Any]:
        return build_setup_for_request(settings, request)

    @app.get("/", tags=["hosted"], response_class=HTMLResponse)
    async def mcp_home(request: Request) -> HTMLResponse:
        slug = resolve_tenant_slug(settings, request)
        if slug and (settings.public_base_url or settings.effective_api_base_url()):
            html = render_hosted_landing(
                tenant_slug=slug,
                public_base_url=settings.public_base_url or settings.effective_api_base_url(),
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
        payload = _setup_payload(request)
        accept = request.headers.get("accept", "")
        wants_json = format == "json" or (
            "application/json" in accept and "text/html" not in accept
        )
        if wants_json:
            return payload
        if settings.server_role == "api":
            portal = settings.effective_portal_base_url()
            return RedirectResponse(f"{portal}/dashboard/setup", status_code=302)
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

    @app.post("/v1/demo/generate", tags=["demo"])
    async def demo_generate(body: DemoGenerateRequest, request: Request) -> dict[str, Any]:
        """Public browser demo (ucpcore.org/try): GitHub issues only, rate-limited."""
        if not settings.demo_enabled:
            raise StarletteHTTPException(404, "demo endpoint is disabled")
        client_ip = request.client.host if request.client else "unknown"
        allowed, retry_after = request.app.state.demo_rate_limiter.check(client_ip)
        if not allowed:
            raise StarletteHTTPException(
                429,
                f"demo rate limit exceeded; retry in {retry_after}s",
            )
        try:
            return generate_demo_package(body.ref, github_token=settings.github_token)
        except ValueError as exc:
            raise StarletteHTTPException(400, str(exc)) from exc

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
            body.source,
            body.ref,
            llm=body.llm,
            since=body.since,
            audience=audience,
            principal=principal if principal != "service" else None,
            tenant_id=_request_tenant_id(request, settings),
            tenant_slug=getattr(request.state, "tenant_slug", None) or settings.tenant_slug,
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

    @app.post("/v1/webhooks/jira", tags=["webhooks"])
    async def jira_webhook(request: Request) -> dict[str, Any]:
        redis_url = _require_webhook_engine(settings)
        body = await request.body()
        from .webhooks import handle_jira_webhook

        try:
            return handle_jira_webhook(
                body=body,
                secret=request.headers.get("X-Webhook-Secret"),
                configured_secret=settings.jira_webhook_secret,
                redis_url=redis_url,
            )
        except PermissionError as exc:
            raise StarletteHTTPException(401, str(exc)) from exc
        except json.JSONDecodeError as exc:
            raise StarletteHTTPException(400, "invalid JSON payload") from exc

    @app.post("/v1/webhooks/confluence", tags=["webhooks"])
    async def confluence_webhook(request: Request) -> dict[str, Any]:
        redis_url = _require_webhook_engine(settings)
        body = await request.body()
        from .webhooks import handle_confluence_webhook

        try:
            return handle_confluence_webhook(
                body=body,
                secret=request.headers.get("X-Webhook-Secret"),
                configured_secret=settings.confluence_webhook_secret,
                redis_url=redis_url,
            )
        except PermissionError as exc:
            raise StarletteHTTPException(401, str(exc)) from exc
        except json.JSONDecodeError as exc:
            raise StarletteHTTPException(400, "invalid JSON payload") from exc

    @app.post("/v1/webhooks/inbound/{source}/{url_token}", tags=["webhooks"])
    async def inbound_webhook(source: str, url_token: str, request: Request) -> dict[str, Any]:
        if source not in VALID_SOURCES:
            raise StarletteHTTPException(404, f"unknown webhook source '{source}'")
        redis_url = _require_webhook_engine(settings)
        store = get_webhook_store(settings)
        resolved = store.resolve(
            source, url_token, tenant_id=getattr(request.state, "tenant_id", None)
        )
        if resolved is None:
            raise StarletteHTTPException(401, "invalid or revoked webhook token")
        _endpoint, signing_secret = resolved
        body = await request.body()
        from .webhooks import handle_inbound_webhook

        try:
            return handle_inbound_webhook(
                source=source,
                body=body,
                signature=request.headers.get("X-Hub-Signature-256", ""),
                signing_secret=signing_secret,
                redis_url=redis_url,
            )
        except PermissionError as exc:
            raise StarletteHTTPException(401, str(exc)) from exc
        except ValueError as exc:
            raise StarletteHTTPException(400, str(exc)) from exc
        except json.JSONDecodeError as exc:
            raise StarletteHTTPException(400, "invalid JSON payload") from exc

    @app.get("/v1/me/connectors", tags=["me"])
    async def me_list_connectors(request: Request) -> dict[str, Any]:
        _me_token_owner(request, settings)
        return list_connectors(settings, tenant_id=_portal_user_tenant_id(request, settings))

    @app.put("/v1/me/connectors/{provider}/scope", tags=["me"])
    async def me_update_connector_scope(
        request: Request,
        provider: str,
        body: MeUpdateConnectorScopeRequest,
    ) -> dict[str, Any]:
        _me_token_owner(request, settings)
        if provider not in CONNECTOR_SPECS:
            raise StarletteHTTPException(404, f"unknown connector: {provider}")
        try:
            scope = update_scope(
                settings,
                provider,
                body.scope,
                tenant_id=_portal_user_tenant_id(request, settings),
            )
        except ValueError as exc:
            raise StarletteHTTPException(404, str(exc)) from exc
        except RuntimeError as exc:
            raise StarletteHTTPException(503, str(exc)) from exc
        return {"provider": provider, "scope": scope}

    @app.get("/v1/me/connectors/{provider}/resources", tags=["me"])
    async def me_list_connector_resources(
        request: Request,
        provider: str,
        field: str = Query(..., min_length=1, max_length=32),
    ) -> dict[str, Any]:
        _me_token_owner(request, settings)
        if provider not in CONNECTOR_SPECS:
            raise StarletteHTTPException(404, f"unknown connector: {provider}")
        try:
            return await list_connector_resources(settings, provider, field)
        except ValueError as exc:
            raise StarletteHTTPException(404, str(exc)) from exc
        except RuntimeError as exc:
            raise StarletteHTTPException(503, str(exc)) from exc

    @app.get("/v1/me/indexing/status", tags=["me"])
    async def me_indexing_status(request: Request) -> dict[str, Any]:
        _me_token_owner(request, settings)
        return get_indexing_status(
            settings,
            tenant_id=_portal_user_tenant_id(request, settings),
            tenant_slug=resolve_tenant_slug(settings, request),
        )

    @app.get("/v1/me/demo-context", tags=["me"])
    async def me_demo_context(request: Request) -> dict[str, Any]:
        principal, _ = _resolve_me_principal(request, settings)
        return build_demo_context(settings, principal, request.app.state.cache)

    @app.get("/v1/me/webhooks", tags=["me"])
    async def me_list_webhooks(request: Request) -> dict[str, Any]:
        user_id, _ = _me_token_owner(request, settings)
        if user_id is None:
            raise StarletteHTTPException(
                403, "webhook setup requires a portal account — sign in at /dashboard"
            )
        store = get_webhook_store(settings)
        return {
            "endpoints": store.list_for_user(user_id),
            "sources": _WEBHOOK_SETUP_HINTS,
            "env_fallback": {
                "github": "/v1/webhooks/github (GITHUB_WEBHOOK_SECRET)",
                "jira": "/v1/webhooks/jira (optional JIRA_WEBHOOK_SECRET)",
                "confluence": "/v1/webhooks/confluence (optional CONFLUENCE_WEBHOOK_SECRET)",
            },
        }

    @app.post("/v1/me/webhooks", tags=["me"])
    async def me_create_webhook(
        request: Request, body: MeCreateWebhookRequest
    ) -> dict[str, Any]:
        user_id, _ = _me_token_owner(request, settings)
        if user_id is None:
            raise StarletteHTTPException(403, "webhook setup requires a portal account")
        store = get_webhook_store(settings)
        try:
            created = store.create(
                user_id=user_id,
                source=body.source,
                label=body.label,
                tenant_id=_request_tenant_id(request, settings),
            )
        except ValueError as exc:
            raise StarletteHTTPException(400, str(exc)) from exc
        hint = _WEBHOOK_SETUP_HINTS.get(body.source, {})
        return {
            "endpoint": created.endpoint.to_public(
                inbound_url_hint=created.inbound_url,
            ),
            "inbound_url": created.inbound_url,
            "signing_secret": created.signing_secret,
            "setup": hint,
            "note": "Save inbound_url and signing_secret now — the URL token cannot be retrieved again.",
        }

    @app.delete("/v1/me/webhooks/{endpoint_id}", tags=["me"])
    async def me_revoke_webhook(request: Request, endpoint_id: str) -> dict[str, str]:
        user_id, _ = _me_token_owner(request, settings)
        if user_id is None:
            raise StarletteHTTPException(403, "webhook setup requires a portal account")
        if not get_webhook_store(settings).revoke(endpoint_id, user_id=user_id):
            raise StarletteHTTPException(404, "webhook endpoint not found")
        return {"status": "revoked", "id": endpoint_id}

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
        payload = _setup_payload(request)
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
        from .token_savings import get_token_savings_store

        token_savings = get_token_savings_store(settings).summary(principal)
        return {
            **summary,
            "daily": stats["daily"],
            "by_channel": stats["by_channel"],
            "generates_logged": stats["generates"],
            "recent_activity": recent,
            "receipts": {"total": len(mine), "outcomes": outcomes},
            "token_savings": token_savings,
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
    async def admin_create_invite(body: CreateInviteRequest, request: Request) -> dict[str, Any]:
        invite_store = get_invite_store(settings)
        tenant_id = getattr(request.state, "tenant_id", None)
        try:
            invite, code = invite_store.create(
                principal_name=body.name,
                scopes=list(body.scopes),
                ttl_hours=body.ttl_hours,
                tenant_id=tenant_id,
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
    app.include_router(build_sidebar_auth_router(settings))
    app.include_router(build_oauth_router(settings))
    app.include_router(build_mcp_oauth_router(settings))

    # --- MCP over Streamable HTTP at /mcp ----------------------------------------
    # Mounted at the root as the last route: FastAPI routes above win, and the
    # MCP endpoint is served at exactly /mcp (no 307 redirect).
    app.mount("/", mcp_app)

    # Middleware wraps everything above, including the MCP mount.
    # CORS must be outermost so 401/403 short-circuits from auth still get ACAO headers.
    token_store = get_token_store(settings)
    hosted = bool(settings.tenant_slug or settings.multi_tenant) and (
        settings.hosted_mode or bool(settings.public_base_url)
    )
    tenant_store = get_tenant_store(settings) if settings.multi_tenant else None
    app.add_middleware(_BodyLimitMiddleware)
    if settings.server_role != "full":
        app.add_middleware(_RoleGateMiddleware, settings=settings)
    if auth_required(settings, token_store):
        app.add_middleware(AuthMiddleware, settings=settings, token_store=token_store)
    if settings.tenant_slug or settings.multi_tenant:
        app.add_middleware(
            TenantPathMiddleware,
            tenant_slug=settings.tenant_slug,
            hosted_mode=hosted,
            multi_tenant=settings.multi_tenant,
            tenant_store=tenant_store,
        )
    app.add_middleware(_ExtensionCorsMiddleware)

    return app
