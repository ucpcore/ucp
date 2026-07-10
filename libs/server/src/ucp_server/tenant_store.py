"""Logical tenants for shared multi-tenant SaaS (0.5.0)."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .config import Settings
from .platform_db import TenantRow, get_session_factory, postgres_available, utcnow


@dataclass(frozen=True)
class Tenant:
    id: str
    slug: str
    name: str
    status: str

    def to_public(self) -> dict[str, Any]:
        return {"id": self.id, "slug": self.slug, "name": self.name, "status": self.status}


def _row_to_tenant(row: TenantRow) -> Tenant:
    return Tenant(id=row.id, slug=row.slug, name=row.name, status=row.status)


class TenantStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.cache_dir.expanduser() / "tenants" / "tenants.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._use_pg = postgres_available(settings.database_url)

    def ensure_tenant(self, *, slug: str, name: Optional[str] = None) -> Tenant:
        existing = self.get_by_slug(slug)
        if existing is not None:
            return existing
        tenant_id = uuid.uuid4().hex[:16]
        display = (name or slug).strip()[:120] or slug
        now = utcnow()
        if self._use_pg:
            session_factory = get_session_factory(self.settings.database_url or "")
            with session_factory() as session:
                row = TenantRow(
                    id=tenant_id,
                    slug=slug,
                    name=display,
                    status="active",
                    created_at=now,
                )
                session.add(row)
                session.commit()
                return _row_to_tenant(row)
        rows = self._load_json()
        record = {
            "id": tenant_id,
            "slug": slug,
            "name": display,
            "status": "active",
            "created_at": now.isoformat().replace("+00:00", "Z"),
        }
        rows.append(record)
        self._save_json(rows)
        return Tenant(**{k: record[k] for k in ("id", "slug", "name", "status")})

    def get_by_slug(self, slug: str) -> Optional[Tenant]:
        if self._use_pg:
            session_factory = get_session_factory(self.settings.database_url or "")
            with session_factory() as session:
                row = (
                    session.query(TenantRow)
                    .filter(TenantRow.slug == slug, TenantRow.status == "active")
                    .one_or_none()
                )
                return _row_to_tenant(row) if row else None
        for row in self._load_json():
            if row.get("slug") == slug and row.get("status", "active") == "active":
                return Tenant(
                    id=row["id"],
                    slug=row["slug"],
                    name=row.get("name") or row["slug"],
                    status=row.get("status", "active"),
                )
        return None

    def get_by_id(self, tenant_id: str) -> Optional[Tenant]:
        if self._use_pg:
            session_factory = get_session_factory(self.settings.database_url or "")
            with session_factory() as session:
                row = session.get(TenantRow, tenant_id)
                return _row_to_tenant(row) if row else None
        for row in self._load_json():
            if row.get("id") == tenant_id:
                return Tenant(
                    id=row["id"],
                    slug=row["slug"],
                    name=row.get("name") or row["slug"],
                    status=row.get("status", "active"),
                )
        return None

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


def get_tenant_store(settings: Settings) -> TenantStore:
    return TenantStore(settings)


def bootstrap_tenants(settings: Settings) -> None:
    """Ensure default tenant from env when multi-tenant mode is on."""
    if not settings.multi_tenant:
        return
    slug = settings.tenant_slug
    if not slug:
        return
    get_tenant_store(settings).ensure_tenant(slug=slug, name=slug)
