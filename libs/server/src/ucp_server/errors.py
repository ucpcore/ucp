"""RFC 9457 problem+json responses."""
from __future__ import annotations

from fastapi.responses import JSONResponse

PROBLEM_TYPE_BASE = "https://ucpcore.org/problems"


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
