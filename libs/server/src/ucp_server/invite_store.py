"""Single-use invite links for personal token onboarding (pilot)."""
from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from .config import Settings
from .platform_db import InviteRow, get_session_factory, postgres_available, utcnow
from .token_store import TOKEN_PREFIX, VALID_SCOPES, TokenStore, get_token_store

INVITE_PREFIX = "inv_"
DEFAULT_TTL_HOURS = 168  # 7 days
DEFAULT_SCOPES = ["generate", "receipt"]


@dataclass
class StoredInvite:
    id: str
    principal_name: str
    scopes: list[str]
    code_hash: str
    created_at: str
    expires_at: str
    redeemed_at: Optional[str] = None
    redeemed_token_id: Optional[str] = None
    redeemed_user_id: Optional[str] = None
    revoked_at: Optional[str] = None

    def to_public(self, *, status: Optional[str] = None) -> dict[str, Any]:
        st = status or _status(self)
        return {
            "id": self.id,
            "principal_name": self.principal_name,
            "scopes": self.scopes,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "redeemed_at": self.redeemed_at,
            "redeemed_token_id": self.redeemed_token_id,
            "redeemed_user_id": self.redeemed_user_id,
            "revoked_at": self.revoked_at,
            "status": st,
        }


def _hash_code(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _status(invite: StoredInvite) -> str:
    if invite.revoked_at:
        return "revoked"
    if invite.redeemed_at:
        return "redeemed"
    if _parse_iso(invite.expires_at) <= datetime.now(timezone.utc):
        return "expired"
    return "pending"


def _validate_invite_create(name: str, scopes: list[str]) -> None:
    name = name.strip()
    if not name:
        raise ValueError("name is required")
    if len(name) > 120:
        raise ValueError("name must be at most 120 characters")
    if not scopes:
        raise ValueError("at least one scope is required")
    bad = set(scopes) - VALID_SCOPES
    if bad:
        raise ValueError(f"invalid scope(s): {', '.join(sorted(bad))}")


class JsonInviteStore:
    def __init__(self, settings: Settings):
        self.path = settings.cache_dir.expanduser() / "invites" / "invites.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.is_file():
            self._write([])

    def list_invites(self) -> list[dict[str, Any]]:
        return [i.to_public() for i in self._load()]

    def create(
        self,
        *,
        principal_name: str,
        scopes: list[str],
        ttl_hours: int = DEFAULT_TTL_HOURS,
    ) -> tuple[StoredInvite, str]:
        _validate_invite_create(principal_name, scopes)
        raw = INVITE_PREFIX + secrets.token_urlsafe(24)
        now = datetime.now(timezone.utc)
        invite = StoredInvite(
            id=uuid.uuid4().hex[:12],
            principal_name=principal_name.strip(),
            scopes=sorted(set(scopes)),
            code_hash=_hash_code(raw),
            created_at=_now_iso(),
            expires_at=(now + timedelta(hours=max(1, ttl_hours))).isoformat().replace("+00:00", "Z"),
        )
        rows = self._load()
        rows.append(invite)
        self._write(rows)
        return invite, raw

    def preview(self, code: str) -> Optional[dict[str, Any]]:
        invite = self._find_by_code(code)
        if invite is None:
            return None
        st = _status(invite)
        if st != "pending":
            return {"status": st, "principal_name": invite.principal_name, "expires_at": invite.expires_at}
        return {
            "status": "pending",
            "principal_name": invite.principal_name,
            "expires_at": invite.expires_at,
            "scopes": invite.scopes,
        }

    def redeem(self, code: str, token_store: TokenStore) -> tuple[StoredInvite, str, dict[str, Any]]:
        invite = self._find_by_code(code)
        if invite is None:
            raise ValueError("invalid or expired invite")
        st = _status(invite)
        if st != "pending":
            raise ValueError(f"invite is {st}")
        token, raw = token_store.create(name=invite.principal_name, scopes=invite.scopes)
        invite.redeemed_at = _now_iso()
        invite.redeemed_token_id = token.id
        rows = self._load()
        updated: list[StoredInvite] = []
        for row in rows:
            if row.id == invite.id:
                updated.append(invite)
            else:
                updated.append(row)
        self._write(updated)
        return invite, raw, token.to_public()

    def mark_redeemed_by_user(self, code: str, user_id: str) -> StoredInvite:
        invite = self._find_by_code(code)
        if invite is None:
            raise ValueError("invalid or expired invite")
        st = _status(invite)
        if st != "pending":
            raise ValueError(f"invite is {st}")
        invite.redeemed_at = _now_iso()
        invite.redeemed_user_id = user_id
        rows = self._load()
        updated: list[StoredInvite] = []
        for row in rows:
            if row.id == invite.id:
                updated.append(invite)
            else:
                updated.append(row)
        self._write(updated)
        return invite

    def revoke(self, invite_id: str) -> bool:
        rows = self._load()
        found = False
        updated: list[StoredInvite] = []
        for row in rows:
            if row.id == invite_id and row.revoked_at is None and row.redeemed_at is None:
                row.revoked_at = _now_iso()
                found = True
            updated.append(row)
        if found:
            self._write(updated)
        return found

    def _find_by_code(self, code: str) -> Optional[StoredInvite]:
        if not code.startswith(INVITE_PREFIX):
            return None
        digest = _hash_code(code)
        for row in self._load():
            if row.code_hash == digest:
                return row
        return None

    def _load(self) -> list[StoredInvite]:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return [
            StoredInvite(
                id=item["id"],
                principal_name=item["principal_name"],
                scopes=list(item["scopes"]),
                code_hash=item["code_hash"],
                created_at=item["created_at"],
                expires_at=item["expires_at"],
                redeemed_at=item.get("redeemed_at"),
                redeemed_token_id=item.get("redeemed_token_id"),
                revoked_at=item.get("revoked_at"),
                redeemed_user_id=item.get("redeemed_user_id"),
            )
            for item in data
        ]

    def _write(self, rows: list[StoredInvite]) -> None:
        payload = [
            {
                "id": r.id,
                "principal_name": r.principal_name,
                "scopes": r.scopes,
                "code_hash": r.code_hash,
                "created_at": r.created_at,
                "expires_at": r.expires_at,
                "redeemed_at": r.redeemed_at,
                "redeemed_token_id": r.redeemed_token_id,
                "redeemed_user_id": r.redeemed_user_id,
                "revoked_at": r.revoked_at,
            }
            for r in rows
        ]
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class PostgresInviteStore:
    def __init__(self, settings: Settings):
        if not settings.database_url:
            raise ValueError("DATABASE_URL is required")
        self.session_factory = get_session_factory(settings.database_url)

    def list_invites(self) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            rows = session.query(InviteRow).order_by(InviteRow.created_at.desc()).all()
            return [self._row_to_public(r) for r in rows]

    def create(
        self,
        *,
        principal_name: str,
        scopes: list[str],
        ttl_hours: int = DEFAULT_TTL_HOURS,
    ) -> tuple[StoredInvite, str]:
        _validate_invite_create(principal_name, scopes)
        raw = INVITE_PREFIX + secrets.token_urlsafe(24)
        now = utcnow()
        invite = StoredInvite(
            id=uuid.uuid4().hex[:12],
            principal_name=principal_name.strip(),
            scopes=sorted(set(scopes)),
            code_hash=_hash_code(raw),
            created_at=now.isoformat().replace("+00:00", "Z"),
            expires_at=(now + timedelta(hours=max(1, ttl_hours))).isoformat().replace("+00:00", "Z"),
        )
        with self.session_factory() as session:
            session.add(
                InviteRow(
                    id=invite.id,
                    code_hash=invite.code_hash,
                    principal_name=invite.principal_name,
                    scopes=json.dumps(invite.scopes),
                    created_at=now,
                    expires_at=_parse_iso(invite.expires_at),
                )
            )
            session.commit()
        return invite, raw

    def preview(self, code: str) -> Optional[dict[str, Any]]:
        invite = self._find_by_code(code)
        if invite is None:
            return None
        st = _status(invite)
        if st != "pending":
            return {"status": st, "principal_name": invite.principal_name, "expires_at": invite.expires_at}
        return {
            "status": "pending",
            "principal_name": invite.principal_name,
            "expires_at": invite.expires_at,
            "scopes": invite.scopes,
        }

    def redeem(self, code: str, token_store: TokenStore) -> tuple[StoredInvite, str, dict[str, Any]]:
        invite = self._find_by_code(code)
        if invite is None:
            raise ValueError("invalid or expired invite")
        st = _status(invite)
        if st != "pending":
            raise ValueError(f"invite is {st}")
        token, raw = token_store.create(name=invite.principal_name, scopes=invite.scopes)
        now = utcnow()
        with self.session_factory() as session:
            row = session.get(InviteRow, invite.id)
            if row is None:
                raise ValueError("invalid or expired invite")
            row.redeemed_at = now
            row.redeemed_token_id = token.id
            session.commit()
        invite.redeemed_at = now.isoformat().replace("+00:00", "Z")
        invite.redeemed_token_id = token.id
        return invite, raw, token.to_public()

    def mark_redeemed_by_user(self, code: str, user_id: str) -> StoredInvite:
        invite = self._find_by_code(code)
        if invite is None:
            raise ValueError("invalid or expired invite")
        st = _status(invite)
        if st != "pending":
            raise ValueError(f"invite is {st}")
        now = utcnow()
        with self.session_factory() as session:
            row = session.get(InviteRow, invite.id)
            if row is None:
                raise ValueError("invalid or expired invite")
            row.redeemed_at = now
            row.redeemed_user_id = user_id
            session.commit()
        invite.redeemed_at = now.isoformat().replace("+00:00", "Z")
        invite.redeemed_user_id = user_id
        return invite

    def revoke(self, invite_id: str) -> bool:
        now = utcnow()
        with self.session_factory() as session:
            row = session.get(InviteRow, invite_id)
            if row is None or row.revoked_at is not None or row.redeemed_at is not None:
                return False
            row.revoked_at = now
            session.commit()
            return True

    def _find_by_code(self, code: str) -> Optional[StoredInvite]:
        if not code.startswith(INVITE_PREFIX):
            return None
        digest = _hash_code(code)
        with self.session_factory() as session:
            row = session.query(InviteRow).filter(InviteRow.code_hash == digest).one_or_none()
            if row is None:
                return None
            return self._row_to_stored(row)

    def _row_to_stored(self, row: InviteRow) -> StoredInvite:
        return StoredInvite(
            id=row.id,
            principal_name=row.principal_name,
            scopes=json.loads(row.scopes),
            code_hash=row.code_hash,
            created_at=row.created_at.isoformat().replace("+00:00", "Z"),
            expires_at=row.expires_at.isoformat().replace("+00:00", "Z"),
            redeemed_at=row.redeemed_at.isoformat().replace("+00:00", "Z") if row.redeemed_at else None,
            redeemed_token_id=row.redeemed_token_id,
            redeemed_user_id=row.redeemed_user_id,
            revoked_at=row.revoked_at.isoformat().replace("+00:00", "Z") if row.revoked_at else None,
        )

    def _row_to_public(self, row: InviteRow) -> dict[str, Any]:
        return self._row_to_stored(row).to_public()


InviteStore = JsonInviteStore | PostgresInviteStore


def get_invite_store(settings: Settings) -> InviteStore:
    if postgres_available(settings.database_url):
        return PostgresInviteStore(settings)
    return JsonInviteStore(settings)


def invite_dashboard_path(code: str) -> str:
    return f"/dashboard/invite?code={code}"


def invite_dashboard_url(settings: Settings, code: str) -> str:
    path = invite_dashboard_path(code)
    if settings.public_base_url:
        return f"{settings.public_base_url.rstrip('/')}{path}"
    return path
