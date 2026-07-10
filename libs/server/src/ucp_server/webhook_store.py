"""User-configured inbound webhook endpoints (per-source URL tokens)."""
from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from .config import Settings
from .platform_db import WebhookEndpointRow, get_session_factory, postgres_available, utcnow
from .tenant import normalize_tenant_slug, public_api_url

WebhookSource = Literal["github", "jira", "confluence"]
VALID_SOURCES = frozenset({"github", "jira", "confluence"})
TOKEN_PREFIX = "in_"
SECRET_PREFIX = "whsec_"


@dataclass(frozen=True)
class WebhookEndpoint:
    id: str
    source: WebhookSource
    label: str
    user_id: str
    created_at: str
    revoked_at: Optional[str] = None

    def to_public(self, *, inbound_url_hint: str) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "label": self.label,
            "inbound_url_hint": inbound_url_hint,
            "created_at": self.created_at,
            "revoked_at": self.revoked_at,
        }


@dataclass(frozen=True)
class CreatedWebhookEndpoint:
    endpoint: WebhookEndpoint
    inbound_url: str
    signing_secret: str


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _api_base_url(settings: Settings) -> Optional[str]:
    if hasattr(settings, "effective_api_base_url"):
        return settings.effective_api_base_url()
    raw = getattr(settings, "api_public_base_url", None) or getattr(
        settings, "public_base_url", None
    )
    return str(raw).rstrip("/") if raw else None


def inbound_webhook_url(settings: Settings, source: str, url_token: str, tenant_slug: Optional[str] = None) -> str:
    path = f"/v1/webhooks/inbound/{source}/{url_token}"
    slug = tenant_slug or (normalize_tenant_slug(settings.tenant_slug) if settings.tenant_slug else None)
    base = _api_base_url(settings)
    if base and slug:
        return public_api_url(base, slug, path)
    fallback = base or f"http://{settings.host}:{settings.port}"
    return f"{fallback.rstrip('/')}{path}"


class WebhookEndpointStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.cache_dir.expanduser() / "webhooks" / "endpoints.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._use_pg = postgres_available(settings.database_url)

    def create(
        self,
        *,
        user_id: str,
        source: WebhookSource,
        label: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> CreatedWebhookEndpoint:
        if source not in VALID_SOURCES:
            raise ValueError(f"unknown webhook source: {source}")
        endpoint_id = uuid.uuid4().hex[:12]
        url_token = TOKEN_PREFIX + secrets.token_urlsafe(24)
        signing_secret = SECRET_PREFIX + secrets.token_urlsafe(24)
        now = utcnow()
        display_label = (label or f"{source} webhook").strip()[:120] or f"{source} webhook"

        if self._use_pg:
            session_factory = get_session_factory(self.settings.database_url or "")
            with session_factory() as session:
                row = WebhookEndpointRow(
                    id=endpoint_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    source=source,
                    label=display_label,
                    token_hash=_hash_token(url_token),
                    signing_secret=signing_secret,
                    created_at=now,
                    revoked_at=None,
                )
                session.add(row)
                session.commit()
        else:
            rows = self._load_json()
            rows.append(
                {
                    "id": endpoint_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "source": source,
                    "label": display_label,
                    "token_hash": _hash_token(url_token),
                    "signing_secret": signing_secret,
                    "created_at": now.isoformat().replace("+00:00", "Z"),
                    "revoked_at": None,
                }
            )
            self._save_json(rows)

        endpoint = WebhookEndpoint(
            id=endpoint_id,
            source=source,
            label=display_label,
            user_id=user_id,
            created_at=now.isoformat().replace("+00:00", "Z"),
        )
        slug = None
        if tenant_id and self._use_pg:
            from .tenant_store import get_tenant_store

            tenant = get_tenant_store(self.settings).get_by_id(tenant_id)
            slug = tenant.slug if tenant else None
        elif tenant_id and not self._use_pg:
            from .tenant_store import get_tenant_store

            tenant = get_tenant_store(self.settings).get_by_id(tenant_id)
            slug = tenant.slug if tenant else None
        return CreatedWebhookEndpoint(
            endpoint=endpoint,
            inbound_url=inbound_webhook_url(
                self.settings, source, url_token, tenant_slug=slug
            ),
            signing_secret=signing_secret,
        )

    def resolve(
        self, source: str, url_token: str, *, tenant_id: Optional[str] = None
    ) -> Optional[tuple[WebhookEndpoint, str]]:
        """Return (endpoint, signing_secret) for a valid inbound URL token."""
        if source not in VALID_SOURCES:
            return None
        token_hash = _hash_token(url_token)
        if self._use_pg:
            session_factory = get_session_factory(self.settings.database_url or "")
            with session_factory() as session:
                query = session.query(WebhookEndpointRow).filter(
                    WebhookEndpointRow.source == source,
                    WebhookEndpointRow.token_hash == token_hash,
                    WebhookEndpointRow.revoked_at.is_(None),
                )
                if tenant_id is not None:
                    query = query.filter(WebhookEndpointRow.tenant_id == tenant_id)
                row = query.one_or_none()
                if row is None:
                    return None
                return _row_to_endpoint(row), row.signing_secret
        for row in self._load_json():
            if (
                row.get("source") == source
                and row.get("token_hash") == token_hash
                and not row.get("revoked_at")
                and (tenant_id is None or row.get("tenant_id") == tenant_id)
            ):
                return (
                    WebhookEndpoint(
                        id=row["id"],
                        source=row["source"],
                        label=row.get("label") or source,
                        user_id=row["user_id"],
                        created_at=row["created_at"],
                    ),
                    row["signing_secret"],
                )
        return None

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        items: list[WebhookEndpoint] = []
        if self._use_pg:
            session_factory = get_session_factory(self.settings.database_url or "")
            with session_factory() as session:
                rows = (
                    session.query(WebhookEndpointRow)
                    .filter(
                        WebhookEndpointRow.user_id == user_id,
                        WebhookEndpointRow.revoked_at.is_(None),
                    )
                    .order_by(WebhookEndpointRow.created_at.desc())
                    .all()
                )
                items = [_row_to_endpoint(r) for r in rows]
        else:
            for row in self._load_json():
                if row.get("user_id") == user_id and not row.get("revoked_at"):
                    items.append(
                        WebhookEndpoint(
                            id=row["id"],
                            source=row["source"],
                            label=row.get("label") or row["source"],
                            user_id=row["user_id"],
                            created_at=row["created_at"],
                        )
                    )
        hint = "…/v1/webhooks/inbound/{source}/<your-token>"
        return [ep.to_public(inbound_url_hint=hint) for ep in items]

    def revoke(self, endpoint_id: str, *, user_id: str) -> bool:
        now = utcnow()
        if self._use_pg:
            session_factory = get_session_factory(self.settings.database_url or "")
            with session_factory() as session:
                row = (
                    session.query(WebhookEndpointRow)
                    .filter(
                        WebhookEndpointRow.id == endpoint_id,
                        WebhookEndpointRow.user_id == user_id,
                        WebhookEndpointRow.revoked_at.is_(None),
                    )
                    .one_or_none()
                )
                if row is None:
                    return False
                row.revoked_at = now
                session.commit()
                return True
        rows = self._load_json()
        found = False
        for row in rows:
            if (
                row.get("id") == endpoint_id
                and row.get("user_id") == user_id
                and not row.get("revoked_at")
            ):
                row["revoked_at"] = now.isoformat().replace("+00:00", "Z")
                found = True
                break
        if found:
            self._save_json(rows)
        return found

    def _load_json(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return list(data) if isinstance(data, list) else []

    def _save_json(self, rows: list[dict[str, Any]]) -> None:
        self.path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def _row_to_endpoint(row: WebhookEndpointRow) -> WebhookEndpoint:
    return WebhookEndpoint(
        id=row.id,
        source=row.source,  # type: ignore[arg-type]
        label=row.label,
        user_id=row.user_id,
        created_at=row.created_at.isoformat().replace("+00:00", "Z"),
    )


def get_webhook_store(settings: Settings) -> WebhookEndpointStore:
    return WebhookEndpointStore(settings)
