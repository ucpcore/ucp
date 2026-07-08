"""Serve built portal static assets."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

_PORTAL_DIST_CANDIDATES = (
    Path(__file__).resolve().parents[4] / "apps" / "portal" / "dist",
    Path(__file__).resolve().parents[0] / "static" / "portal",
)


def resolve_portal_dist() -> Optional[Path]:
    for candidate in _PORTAL_DIST_CANDIDATES:
        index = candidate / "index.html"
        if index.is_file():
            return candidate
    return None
