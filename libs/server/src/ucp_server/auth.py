"""Bearer authentication: legacy API key or scoped personal tokens."""
from __future__ import annotations

import secrets
from typing import Any, Optional

import contextvars

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .access_audit import get_access_audit_store
from .config import Settings
from .token_store import SERVICE_PRINCIPAL, AuthContext, TokenStore, get_token_store

_current_auth: contextvars.ContextVar[Optional[AuthContext]] = contextvars.ContextVar(
    "_current_auth", default=None
)


def get_current_auth() -> Optional[AuthContext]:
    return _current_auth.get()

UNAUTHENTICATED_PATHS = frozenset({"/healthz", "/readyz", "/admin", "/", "/setup"})

# Paths that accept any valid Bearer (personal or service), no extra scope.
_AUTH_ONLY_PREFIXES: list[tuple[str, str]] = [
    ("GET", "/v1/billing/subscription"),
    ("GET", "/v1/me/"),
]

# Self-service token bootstrap when no tokens exist yet.
_BOOTSTRAP_PATHS = frozenset({("POST", "/v1/me/tokens")})
_SCOPE_RULES: list[tuple[str, str, frozenset[str]]] = [
    ("POST", "/v1/generate", frozenset({"generate"})),
    ("POST", "/v1/receipt", frozenset({"receipt"})),
    ("GET", "/v1/packages", frozenset({"generate"})),
    ("GET", "/v1/admin/", frozenset({"admin:read"})),
]

# Service-only mutations (legacy API key).
_SERVICE_ONLY_PREFIXES = (
    ("POST", "/v1/admin/tokens"),
    ("DELETE", "/v1/admin/tokens/"),
    ("POST", "/v1/admin/invites"),
    ("GET", "/v1/admin/invites"),
    ("DELETE", "/v1/admin/invites/"),
    ("POST", "/v1/admin/sync/"),
    ("POST", "/v1/billing/portal"),
)


def is_auth_only(method: str, path: str) -> bool:
    for rule_method, prefix in _AUTH_ONLY_PREFIXES:
        if method == rule_method and path.startswith(prefix):
            return True
    return False


def is_bootstrap_path(method: str, path: str) -> bool:
    return (method, path) in _BOOTSTRAP_PATHS


def auth_required(settings: Settings, token_store: TokenStore) -> bool:
    return bool(settings.api_key) or token_store.has_active_tokens()


def resolve_auth(settings: Settings, token_store: TokenStore, bearer: str) -> Optional[AuthContext]:
    if settings.api_key and secrets.compare_digest(bearer.encode(), settings.api_key.encode()):
        return AuthContext(
            principal=SERVICE_PRINCIPAL,
            scopes=frozenset({"generate", "receipt", "admin:read"}),
            is_service=True,
        )
    return token_store.resolve(bearer)


def required_scopes(method: str, path: str) -> Optional[frozenset[str]]:
    for rule_method, prefix, scopes in _SCOPE_RULES:
        if method == rule_method and path.startswith(prefix):
            return scopes
    if path.startswith("/mcp"):
        return frozenset({"generate"})
    return None


def is_service_only(method: str, path: str) -> bool:
    for rule_method, prefix in _SERVICE_ONLY_PREFIXES:
        if method == rule_method and path.startswith(prefix):
            return True
    return False


def is_public_path(method: str, path: str) -> bool:
    if path in UNAUTHENTICATED_PATHS or path.startswith(("/dashboard", "/billing")):
        return True
    if path.startswith("/.well-known/"):
        return True
    if path.startswith("/v1/oauth/") or path.startswith("/v1/auth/"):
        return True
    if method == "GET" and path == "/v1/billing/plans":
        return True
    if method == "POST" and path == "/v1/billing/webhook/stripe":
        return True
    if method == "POST" and path == "/v1/webhooks/github":
        return True
    if method == "POST" and path == "/v1/webhooks/jira":
        return True
    if method == "POST" and path == "/v1/webhooks/confluence":
        return True
    if method == "POST" and path.startswith("/v1/webhooks/inbound/"):
        return True
    if method == "POST" and path == "/v1/billing/simulate-payment":
        return True
    if method == "POST" and path == "/v1/billing/checkout":
        return True
    if method == "GET" and path == "/v1/me/bootstrap-available":
        return True
    if method == "GET" and path == "/v1/me/invites/preview":
        return True
    return False


def _portal_session_allowed(method: str, path: str) -> bool:
    if path.startswith("/v1/me/"):
        return True
    if method == "GET" and path == "/v1/billing/subscription":
        return True
    if method == "POST" and path in ("/v1/billing/checkout", "/v1/billing/portal"):
        return True
    return False


def scopes_satisfied(auth: AuthContext, needed: frozenset[str]) -> bool:
    if auth.is_service:
        return True
    return needed.issubset(auth.scopes)


class AuthMiddleware(BaseHTTPMiddleware):
    """Validate Bearer credentials and enforce scopes."""

    def __init__(self, app: Any, settings: Settings, token_store: TokenStore):
        super().__init__(app)
        self.settings = settings
        self.token_store = token_store

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        from .errors import problem

        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path
        method = request.method
        if is_public_path(method, path):
            return await call_next(request)
        if path in UNAUTHENTICATED_PATHS:
            return await call_next(request)

        from .portal_session import read_session_cookie

        portal_session = read_session_cookie(request, self.settings)
        if portal_session is not None:
            request.state.portal_session = portal_session
            if _portal_session_allowed(method, path):
                return await call_next(request)

        bootstrap = is_bootstrap_path(method, path)
        if bootstrap and not self.token_store.has_active_tokens():
            return await call_next(request)

        header = request.headers.get("authorization", "")
        scheme, _, credentials = header.partition(" ")
        supplied = credentials.strip() if scheme.lower() == "bearer" else ""

        auth = resolve_auth(self.settings, self.token_store, supplied) if supplied else None
        if auth is None:
            if path == "/mcp" or path.startswith("/mcp/"):
                from .mcp_oauth import mcp_unauthorized_response

                return mcp_unauthorized_response(self.settings)
            return problem(
                401,
                "Unauthorized",
                "Provide 'Authorization: Bearer <UCP_SERVER_API_KEY>' or a personal token (ctx_…).",
                "unauthorized",
            )

        path = request.url.path
        method = request.method

        if is_service_only(method, path) and not auth.is_service:
            return problem(
                403,
                "Forbidden",
                "This endpoint requires the service API key (UCP_SERVER_API_KEY).",
                "forbidden",
            )

        needed = required_scopes(method, path)
        if needed and not is_auth_only(method, path) and not scopes_satisfied(auth, needed):
            return problem(
                403,
                "Forbidden",
                f"Token lacks required scope(s): {', '.join(sorted(needed - auth.scopes))}.",
                "forbidden",
            )

        request.state.auth = auth
        ctx = _current_auth.set(auth)
        try:
            response = await call_next(request)
        finally:
            _current_auth.reset(ctx)

        if not auth.is_service and path.startswith(("/v1/", "/mcp")):
            get_access_audit_store(self.settings).append(
                principal=auth.principal,
                method=method,
                path=path,
                status=response.status_code,
                token_id=auth.token_id,
            )
        return response
