"""Personal API tokens (alpha.12.1) — hashed secrets, scoped access."""
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

TOKEN_PREFIX = "ctx_"
VALID_SCOPES = frozenset({"generate", "receipt", "admin:read"})
SERVICE_PRINCIPAL = "service"


AuthMethod = Literal["oauth", "manual"]


@dataclass(frozen=True)
class AuthContext:
    """Resolved principal after Bearer validation."""

    principal: str
    scopes: frozenset[str]
    is_service: bool
    token_id: Optional[str] = None


@dataclass
class StoredToken:
    id: str
    name: str
    scopes: list[str]
    secret_hash: str
    created_at: str
    revoked_at: Optional[str] = None
    last_used_at: Optional[str] = None
    user_id: Optional[str] = None
    client_label: Optional[str] = None
    auth_method: Optional[str] = None

    def to_public(self) -> dict[str, Any]:
        return _token_to_public(self)


def _device_label(name: str, client_label: Optional[str]) -> str:
    if client_label:
        return client_label
    if " (" in name:
        return name.split(" (", 1)[1].rstrip(")")
    return "Legacy"


def _token_to_public(token: StoredToken | Any) -> dict[str, Any]:
    name = token.name
    client_label = getattr(token, "client_label", None)
    auth_method = getattr(token, "auth_method", None) or "manual"
    scopes = token.scopes if isinstance(token.scopes, list) else _scopes_from_str(token.scopes)
    created_at = token.created_at if isinstance(token.created_at, str) else _dt_iso(token.created_at)
    revoked_at = token.revoked_at
    if revoked_at is not None and not isinstance(revoked_at, str):
        revoked_at = _dt_iso(revoked_at)
    last_used_at = token.last_used_at
    if last_used_at is not None and not isinstance(last_used_at, str):
        last_used_at = _dt_iso(last_used_at)
    return {
        "id": token.id,
        "name": name,
        "scopes": scopes,
        "created_at": created_at,
        "revoked_at": revoked_at,
        "last_used_at": last_used_at,
        "user_id": getattr(token, "user_id", None),
        "client_label": _device_label(name, client_label),
        "auth_method": auth_method,
    }


def _token_owned_by(
    *,
    user_id: Optional[str],
    principal: str,
    token_user_id: Optional[str],
    token_name: str,
) -> bool:
    if user_id and token_user_id == user_id:
        return True
    if token_user_id is None:
        if token_name == principal:
            return True
        if token_name.startswith(f"{principal} ("):
            return True
    return False


def _hash_secret(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class JsonTokenStore:
    """JSON file under cache_dir/tokens/tokens.json (fallback without DATABASE_URL)."""

    def __init__(self, settings: Settings):
        self.path = settings.cache_dir.expanduser() / "tokens" / "tokens.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.is_file():
            self._write([])

    def has_active_tokens(self) -> bool:
        return any(t.revoked_at is None for t in self._load())

    def list_tokens(self) -> list[dict[str, Any]]:
        return [t.to_public() for t in self._load() if t.revoked_at is None]

    def list_for_principal(self, principal: str) -> list[dict[str, Any]]:
        return self.list_for_user(None, principal)

    def list_for_user(self, user_id: Optional[str], principal: str) -> list[dict[str, Any]]:
        return [
            t.to_public()
            for t in self._load()
            if t.revoked_at is None
            and _token_owned_by(
                user_id=user_id,
                principal=principal,
                token_user_id=t.user_id,
                token_name=t.name,
            )
        ]

    def get_user_id_for_token(self, token_id: Optional[str]) -> Optional[str]:
        if not token_id:
            return None
        for row in self._load():
            if row.id == token_id and row.revoked_at is None:
                return row.user_id
        return None

    def revoke_for_principal(self, token_id: str, principal: str) -> bool:
        return self.revoke_for_user(token_id, None, principal)

    def revoke_for_user(self, token_id: str, user_id: Optional[str], principal: str) -> bool:
        rows = self._load()
        found = False
        updated: list[StoredToken] = []
        for row in rows:
            if (
                row.id == token_id
                and row.revoked_at is None
                and _token_owned_by(
                    user_id=user_id,
                    principal=principal,
                    token_user_id=row.user_id,
                    token_name=row.name,
                )
            ):
                row.revoked_at = _now_iso()
                found = True
            updated.append(row)
        if found:
            self._write(updated)
        return found

    def revoke_all_for_principal(self, principal: str) -> int:
        return self.revoke_all_for_user(None, principal)

    def revoke_all_for_user(self, user_id: Optional[str], principal: str) -> int:
        rows = self._load()
        count = 0
        updated: list[StoredToken] = []
        for row in rows:
            if row.revoked_at is None and _token_owned_by(
                user_id=user_id,
                principal=principal,
                token_user_id=row.user_id,
                token_name=row.name,
            ):
                row.revoked_at = _now_iso()
                count += 1
            updated.append(row)
        if count:
            self._write(updated)
        return count

    def create(
        self,
        *,
        name: str,
        scopes: list[str],
        user_id: Optional[str] = None,
        client_label: Optional[str] = None,
        auth_method: AuthMethod = "manual",
    ) -> tuple[StoredToken, str]:
        _validate_token_create(name, scopes)
        raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
        token = StoredToken(
            id=uuid.uuid4().hex[:12],
            name=name.strip(),
            scopes=sorted(set(scopes)),
            secret_hash=_hash_secret(raw),
            created_at=_now_iso(),
            user_id=user_id,
            client_label=client_label,
            auth_method=auth_method,
        )
        rows = self._load()
        rows.append(token)
        self._write(rows)
        return token, raw

    def revoke(self, token_id: str) -> bool:
        rows = self._load()
        found = False
        updated: list[StoredToken] = []
        for row in rows:
            if row.id == token_id and row.revoked_at is None:
                row.revoked_at = _now_iso()
                found = True
            updated.append(row)
        if found:
            self._write(updated)
        return found

    def resolve(self, bearer: str) -> Optional[AuthContext]:
        if not bearer.startswith(TOKEN_PREFIX):
            return None
        digest = _hash_secret(bearer)
        rows = self._load()
        for idx, row in enumerate(rows):
            if row.revoked_at is not None:
                continue
            if not secrets.compare_digest(row.secret_hash, digest):
                continue
            row.last_used_at = _now_iso()
            rows[idx] = row
            self._write(rows)
            return AuthContext(
                principal=row.name,
                scopes=frozenset(row.scopes),
                is_service=False,
                token_id=row.id,
            )
        return None

    def _load(self) -> list[StoredToken]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        rows: list[StoredToken] = []
        for item in data if isinstance(data, list) else []:
            try:
                rows.append(
                    StoredToken(
                        id=str(item["id"]),
                        name=str(item["name"]),
                        scopes=list(item.get("scopes") or []),
                        secret_hash=str(item["secret_hash"]),
                        created_at=str(item.get("created_at") or ""),
                        revoked_at=item.get("revoked_at"),
                        last_used_at=item.get("last_used_at"),
                        user_id=item.get("user_id"),
                        client_label=item.get("client_label"),
                        auth_method=item.get("auth_method"),
                    )
                )
            except (KeyError, TypeError):
                continue
        return rows

    def _write(self, rows: list[StoredToken]) -> None:
        payload = [
            {
                "id": t.id,
                "name": t.name,
                "scopes": t.scopes,
                "secret_hash": t.secret_hash,
                "created_at": t.created_at,
                "revoked_at": t.revoked_at,
                "last_used_at": t.last_used_at,
                "user_id": t.user_id,
                "client_label": t.client_label,
                "auth_method": t.auth_method,
            }
            for t in rows
        ]
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# Back-compat alias
TokenStore = JsonTokenStore


def _scopes_to_str(scopes: list[str]) -> str:
    return ",".join(sorted(set(scopes)))


def _scopes_from_str(raw: str) -> list[str]:
    return [s for s in raw.split(",") if s]


class PostgresTokenStore:
    """Personal tokens in Postgres (platform_personal_tokens)."""

    def __init__(self, settings: Settings):
        from .platform_db import PersonalTokenRow, get_session_factory

        self.settings = settings
        self._Session = get_session_factory(settings.database_url)
        self._migrate_json_if_empty()

    def _migrate_json_if_empty(self) -> None:
        from .platform_db import PersonalTokenRow, utcnow

        json_path = self.settings.cache_dir / "tokens" / "tokens.json"
        with self._Session() as session:
            if session.query(PersonalTokenRow).count() > 0:
                return
        if not json_path.is_file():
            return
        legacy = JsonTokenStore(self.settings)
        rows = legacy._load()
        if not rows:
            return

        with self._Session() as session:
            for row in rows:
                session.add(
                    PersonalTokenRow(
                        id=row.id,
                        name=row.name,
                        scopes=_scopes_to_str(row.scopes),
                        secret_hash=row.secret_hash,
                        created_at=datetime.fromisoformat(
                            row.created_at.replace("Z", "+00:00")
                        )
                        if row.created_at
                        else utcnow(),
                        revoked_at=datetime.fromisoformat(
                            row.revoked_at.replace("Z", "+00:00")
                        )
                        if row.revoked_at
                        else None,
                        last_used_at=datetime.fromisoformat(
                            row.last_used_at.replace("Z", "+00:00")
                        )
                        if row.last_used_at
                        else None,
                    )
                )
            session.commit()

    def has_active_tokens(self) -> bool:
        from .platform_db import PersonalTokenRow

        with self._Session() as session:
            return (
                session.query(PersonalTokenRow)
                .filter(PersonalTokenRow.revoked_at.is_(None))
                .count()
                > 0
            )

    def list_tokens(self) -> list[dict[str, Any]]:
        from .platform_db import PersonalTokenRow

        with self._Session() as session:
            rows = (
                session.query(PersonalTokenRow)
                .filter(PersonalTokenRow.revoked_at.is_(None))
                .all()
            )
            return [_token_to_public(r) for r in rows]

    def list_for_principal(self, principal: str) -> list[dict[str, Any]]:
        return self.list_for_user(None, principal)

    def list_for_user(self, user_id: Optional[str], principal: str) -> list[dict[str, Any]]:
        from .platform_db import PersonalTokenRow

        with self._Session() as session:
            rows = (
                session.query(PersonalTokenRow)
                .filter(PersonalTokenRow.revoked_at.is_(None))
                .all()
            )
            owned = [
                r
                for r in rows
                if _token_owned_by(
                    user_id=user_id,
                    principal=principal,
                    token_user_id=r.user_id,
                    token_name=r.name,
                )
            ]
            return [_token_to_public(r) for r in owned]

    def get_user_id_for_token(self, token_id: Optional[str]) -> Optional[str]:
        if not token_id:
            return None
        from .platform_db import PersonalTokenRow

        with self._Session() as session:
            row = (
                session.query(PersonalTokenRow)
                .filter(
                    PersonalTokenRow.id == token_id,
                    PersonalTokenRow.revoked_at.is_(None),
                )
                .one_or_none()
            )
            return row.user_id if row else None

    def revoke_for_principal(self, token_id: str, principal: str) -> bool:
        return self.revoke_for_user(token_id, None, principal)

    def revoke_for_user(self, token_id: str, user_id: Optional[str], principal: str) -> bool:
        from .platform_db import PersonalTokenRow, utcnow

        with self._Session() as session:
            row = (
                session.query(PersonalTokenRow)
                .filter(
                    PersonalTokenRow.id == token_id,
                    PersonalTokenRow.revoked_at.is_(None),
                )
                .one_or_none()
            )
            if row is None:
                return False
            if not _token_owned_by(
                user_id=user_id,
                principal=principal,
                token_user_id=row.user_id,
                token_name=row.name,
            ):
                return False
            row.revoked_at = utcnow()
            session.commit()
            return True

    def revoke_all_for_principal(self, principal: str) -> int:
        return self.revoke_all_for_user(None, principal)

    def revoke_all_for_user(self, user_id: Optional[str], principal: str) -> int:
        from .platform_db import PersonalTokenRow, utcnow

        with self._Session() as session:
            rows = (
                session.query(PersonalTokenRow)
                .filter(PersonalTokenRow.revoked_at.is_(None))
                .all()
            )
            count = 0
            for row in rows:
                if _token_owned_by(
                    user_id=user_id,
                    principal=principal,
                    token_user_id=row.user_id,
                    token_name=row.name,
                ):
                    row.revoked_at = utcnow()
                    count += 1
            session.commit()
            return count

    def create(
        self,
        *,
        name: str,
        scopes: list[str],
        user_id: Optional[str] = None,
        client_label: Optional[str] = None,
        auth_method: AuthMethod = "manual",
    ) -> tuple[StoredToken, str]:
        _validate_token_create(name, scopes)
        from .platform_db import PersonalTokenRow, utcnow

        raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
        now = utcnow()
        row = PersonalTokenRow(
            id=uuid.uuid4().hex[:12],
            name=name.strip(),
            user_id=user_id,
            client_label=client_label,
            auth_method=auth_method,
            scopes=_scopes_to_str(scopes),
            secret_hash=_hash_secret(raw),
            created_at=now,
        )
        with self._Session() as session:
            session.add(row)
            session.commit()
        token = StoredToken(
            id=row.id,
            name=row.name,
            scopes=_scopes_from_str(row.scopes),
            secret_hash=row.secret_hash,
            created_at=_dt_iso(row.created_at),
            user_id=row.user_id,
            client_label=row.client_label,
            auth_method=row.auth_method,
        )
        return token, raw

    def revoke(self, token_id: str) -> bool:
        from .platform_db import PersonalTokenRow, utcnow

        with self._Session() as session:
            row = (
                session.query(PersonalTokenRow)
                .filter(
                    PersonalTokenRow.id == token_id,
                    PersonalTokenRow.revoked_at.is_(None),
                )
                .one_or_none()
            )
            if row is None:
                return False
            row.revoked_at = utcnow()
            session.commit()
            return True

    def resolve(self, bearer: str) -> Optional[AuthContext]:
        if not bearer.startswith(TOKEN_PREFIX):
            return None
        from .platform_db import PersonalTokenRow, utcnow

        digest = _hash_secret(bearer)
        with self._Session() as session:
            row = (
                session.query(PersonalTokenRow)
                .filter(
                    PersonalTokenRow.revoked_at.is_(None),
                    PersonalTokenRow.secret_hash == digest,
                )
                .one_or_none()
            )
            if row is None:
                return None
            row.last_used_at = utcnow()
            session.commit()
            return AuthContext(
                principal=row.name,
                scopes=frozenset(_scopes_from_str(row.scopes)),
                is_service=False,
                token_id=row.id,
            )


def _validate_token_create(name: str, scopes: list[str]) -> None:
    name = name.strip()
    if not name:
        raise ValueError("token name is required")
    if len(name) > 120:
        raise ValueError("token name exceeds 120 characters")
    unknown = [s for s in scopes if s not in VALID_SCOPES]
    if unknown:
        raise ValueError(f"unknown scopes: {', '.join(unknown)}")
    if not scopes:
        raise ValueError("at least one scope is required")


def _dt_iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")



def _row_to_public(row: Any) -> dict[str, Any]:
    return _token_to_public(row)


def get_token_store(settings: Settings) -> JsonTokenStore | PostgresTokenStore:
    from .platform_db import postgres_available

    if postgres_available(settings.database_url):
        return PostgresTokenStore(settings)
    return JsonTokenStore(settings)
