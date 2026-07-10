"""Signed portal session cookies (local login today, SSO claims tomorrow)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Optional

from starlette.requests import Request
from starlette.responses import Response

from .config import Settings
from .user_store import PortalUser

SESSION_COOKIE = "ucp_portal_session"


@dataclass(frozen=True)
class PortalSession:
    user_id: str
    email: str
    display_name: str
    role: str
    auth_provider: str

    @classmethod
    def from_user(cls, user: PortalUser) -> PortalSession:
        return cls(
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=user.role,
            auth_provider=user.auth_provider,
        )


def resolve_session_secret(settings: Settings) -> str:
    if settings.session_secret:
        return settings.session_secret
    if settings.api_key:
        return hashlib.sha256(f"portal:{settings.api_key}".encode()).hexdigest()
    # Stable dev fallback — must not change between encode/decode in one process.
    cache_key = str(settings.cache_dir.expanduser().resolve())
    return hashlib.sha256(f"portal-ephemeral:{cache_key}".encode()).hexdigest()


def encode_session(session: PortalSession, settings: Settings) -> str:
    secret = resolve_session_secret(settings)
    payload = {
        "uid": session.user_id,
        "email": session.email,
        "name": session.display_name,
        "role": session.role,
        "ap": session.auth_provider,
        "exp": int(time.time()) + settings.session_ttl_hours * 3600,
    }
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def decode_session(token: str, settings: Settings) -> Optional[PortalSession]:
    secret = resolve_session_secret(settings)
    try:
        body, sig = token.rsplit(".", 1)
        expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        padded = body + "=" * (-len(body) % 4)
        payload: dict[str, Any] = json.loads(base64.urlsafe_b64decode(padded.encode()))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return PortalSession(
            user_id=str(payload["uid"]),
            email=str(payload["email"]),
            display_name=str(payload["name"]),
            role=str(payload.get("role", "member")),
            auth_provider=str(payload.get("ap", "local")),
        )
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


def read_session_cookie(request: Request, settings: Settings) -> Optional[PortalSession]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return decode_session(token, settings)


def set_session_cookie(response: Response, session: PortalSession, settings: Settings) -> None:
    token = encode_session(session, settings)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=bool(settings.public_base_url and settings.public_base_url.startswith("https")),
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE, path="/")
