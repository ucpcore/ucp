"""FastAPI application: versioned REST API + MCP over Streamable HTTP.

Errors follow RFC 9457 (application/problem+json). When UCP_SERVER_API_KEY
is set, every endpoint except the health probes requires a Bearer key,
compared in constant time.
"""
from __future__ import annotations

import os
import secrets
from typing import Any, Literal, Optional

import ucp
from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from . import __version__
from .cache import PackageCache
from .config import MAX_BODY_BYTES, Settings, load_settings
from .mcp_tools import build_mcp
from .service import GenerationService, InvalidRefError, SourceError

PROBLEM_TYPE_BASE = "https://ucpcore.org/problems"
UNAUTHENTICATED_PATHS = frozenset({"/healthz", "/readyz"})


def problem(
    status: int, title: str, detail: str, type_slug: str = "about:blank"
) -> JSONResponse:
    type_uri = (
        type_slug if type_slug == "about:blank" else f"{PROBLEM_TYPE_BASE}/{type_slug}"
    )
    return JSONResponse(
        status_code=status,
        content={"type": type_uri, "title": title, "status": status, "detail": detail},
        media_type="application/problem+json",
    )


class GenerateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    source: Literal["github", "jira"]
    ref: str = Field(min_length=1, max_length=200,
                     description="owner/repo#123 for GitHub, PROJ-123 for Jira")
    llm: bool = False
    since: Optional[str] = Field(default=None, max_length=64,
                                 description="ISO timestamp: add a context_diff since this moment")
    audience: Optional[str] = Field(default=None, max_length=200,
                                    description="Optional audience principal id recorded in the package")


class _AuthMiddleware(BaseHTTPMiddleware):
    """Bearer auth for everything except the health probes (constant-time)."""

    def __init__(self, app: Any, api_key: str):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if request.url.path in UNAUTHENTICATED_PATHS:
            return await call_next(request)
        header = request.headers.get("authorization", "")
        scheme, _, credentials = header.partition(" ")
        supplied = credentials.strip() if scheme.lower() == "bearer" else ""
        if not secrets.compare_digest(supplied.encode(), self.api_key.encode()):
            return problem(
                401,
                "Unauthorized",
                "This server requires 'Authorization: Bearer <UCP_SERVER_API_KEY>'.",
                "unauthorized",
            )
        return await call_next(request)


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

    # path="/mcp" + mount at "/" (below) => the endpoint is exactly /mcp,
    # with no trailing-slash redirect that some MCP clients refuse to follow.
    mcp_app = build_mcp(service).http_app(path="/mcp", stateless_http=True)

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
    async def generate(body: GenerateRequest, response: Response) -> dict[str, Any]:
        entry_id, package, cached = service.generate(
            body.source, body.ref, llm=body.llm, since=body.since, audience=body.audience
        )
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

    # --- MCP over Streamable HTTP at /mcp ----------------------------------------
    # Mounted at the root as the last route: FastAPI routes above win, and the
    # MCP endpoint is served at exactly /mcp (no 307 redirect).
    app.mount("/", mcp_app)

    # Middleware wraps everything above, including the MCP mount.
    app.add_middleware(_BodyLimitMiddleware)
    if settings.api_key:
        app.add_middleware(_AuthMiddleware, api_key=settings.api_key)

    return app
