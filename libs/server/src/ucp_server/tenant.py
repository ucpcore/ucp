"""Hosted pilot: tenant-scoped public URLs (RFC-0009, dedicated VM)."""
from __future__ import annotations

import re
from typing import Any, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .errors import problem

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

# Never rewritten; always reachable at the container root for probes and landing.
_ROOT_PATHS = frozenset({"/", "/healthz", "/readyz", "/setup"})

# MCP OAuth + portal auth stay at root (Cursor PRM discovery uses these URLs).
_HOSTED_ROOT_API_PREFIXES = (
    "/v1/oauth/mcp",
    "/v1/auth",
    "/.well-known/",
)


def normalize_tenant_slug(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    slug = value.strip().lower()
    if not slug:
        return None
    if not _SLUG_RE.fullmatch(slug):
        raise ValueError(
            "UCP_TENANT_SLUG must be 1–63 chars: lowercase letters, digits, hyphens; "
            "must start and end with a letter or digit"
        )
    return slug


# Global /v1 routes without a tenant slug prefix (see extract_tenant_slug_from_path).


def extract_tenant_slug_from_path(path: str) -> Optional[str]:
    """First path segment after /v1/ if it looks like a tenant slug."""
    if not path.startswith("/v1/"):
        return None
    rest = path[4:]
    if not rest:
        return None
    segment = rest.split("/", 1)[0]
    if segment in {"oauth", "auth", "webhooks", "billing", "admin", "me", "generate", "receipt", "packages"}:
        return None
    if _SLUG_RE.fullmatch(segment):
        return segment
    return None


def rewrite_tenant_path(path: str, slug: str) -> Optional[str]:
    """Map public `/v1/{slug}/…` paths to internal ucp-server routes."""
    prefix = f"/v1/{slug}"
    if path == prefix:
        return "/"
    if not path.startswith(prefix + "/"):
        return None
    rest = path[len(prefix) :]
    if rest == "/mcp" or rest.startswith("/mcp/"):
        return rest
    if rest in ("/admin", "/setup") or rest.startswith("/admin/"):
        return rest
    if rest.startswith("/v1/"):
        return rest
    if rest.startswith("/"):
        return f"/v1{rest}"
    return None


def public_mcp_url(public_base_url: str, slug: str) -> str:
    base = public_base_url.rstrip("/")
    return f"{base}/v1/{slug}/mcp"


def public_api_url(public_base_url: str, slug: str, suffix: str) -> str:
    base = public_base_url.rstrip("/")
    path = suffix if suffix.startswith("/") else f"/{suffix}"
    if path.startswith("/v1/"):
        return f"{base}/v1/{slug}{path}"
    return f"{base}/v1/{slug}{path}"


class TenantPathMiddleware(BaseHTTPMiddleware):
    """Rewrite `/v1/{tenant_slug}/…` to internal paths; block legacy URLs in hosted mode."""

    def __init__(
        self,
        app: Any,
        *,
        tenant_slug: Optional[str],
        hosted_mode: bool,
        multi_tenant: bool = False,
        tenant_store: Any = None,
    ):
        super().__init__(app)
        self.tenant_slug = tenant_slug
        self.hosted_mode = hosted_mode
        self.multi_tenant = multi_tenant
        self.tenant_store = tenant_store

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        path = request.url.path

        if path in _ROOT_PATHS or path.startswith("/setup"):
            return await call_next(request)

        if any(path.startswith(prefix) for prefix in _HOSTED_ROOT_API_PREFIXES):
            return await call_next(request)

        slug: Optional[str] = None
        if self.multi_tenant:
            slug = extract_tenant_slug_from_path(path)
            if slug and self.tenant_store is not None:
                tenant = self.tenant_store.get_by_slug(slug)
                if tenant is None:
                    return problem(
                        404,
                        "Tenant Not Found",
                        f"Unknown tenant slug '{slug}'.",
                        "tenant-not-found",
                    )
                request.state.tenant_id = tenant.id
                request.state.tenant_slug = tenant.slug
                rewritten = rewrite_tenant_path(path, slug)
                if rewritten is not None:
                    request.scope["path"] = rewritten
                    request.scope["raw_path"] = rewritten.encode()
                    return await call_next(request)
        elif self.tenant_slug:
            rewritten = rewrite_tenant_path(path, self.tenant_slug)
            if rewritten is not None:
                request.scope["path"] = rewritten
                request.scope["raw_path"] = rewritten.encode()
                return await call_next(request)

        if self.hosted_mode and (
            path in ("/mcp", "/admin")
            or path.startswith(("/mcp/", "/v1/", "/admin/"))
        ):
            hint = "/v1/{tenant_slug}"
            if self.tenant_slug:
                hint = f"/v1/{self.tenant_slug}"
            return problem(
                404,
                "Hosted API Relocated",
                f"Use tenant-scoped URLs under {hint}/ (e.g. {hint}/mcp).",
                "hosted-path-required",
            )

        return await call_next(request)
