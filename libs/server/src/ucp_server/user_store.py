"""Portal user accounts — local password + SSO-ready identity fields."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from .config import Settings
from .platform_db import UserRow, get_session_factory, postgres_available, utcnow

Role = Literal["admin", "member"]
AuthProvider = Literal["local", "oidc"]

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ph = PasswordHasher()


@dataclass(frozen=True)
class PortalUser:
    id: str
    email: str
    display_name: str
    role: Role
    auth_provider: AuthProvider
    external_subject: Optional[str] = None
    external_issuer: Optional[str] = None

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "display_name": self.display_name,
            "role": self.role,
            "auth_provider": self.auth_provider,
            "external_subject": self.external_subject,
            "external_issuer": self.external_issuer,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_email(email: str) -> str:
    normalized = email.strip().lower()
    if not _EMAIL_RE.fullmatch(normalized):
        raise ValueError("invalid email address")
    return normalized


def _validate_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")


def _hash_password(password: str) -> str:
    _validate_password(password)
    return _ph.hash(password)


def _verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


class JsonUserStore:
    def __init__(self, settings: Settings):
        self.path = settings.cache_dir.expanduser() / "users" / "users.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.is_file():
            self._write([])

    def has_users(self) -> bool:
        return len(self._load()) > 0

    def get_by_id(self, user_id: str) -> Optional[PortalUser]:
        for row in self._load():
            if row["id"] == user_id:
                return self._row_to_user(row)
        return None

    def get_by_email(self, email: str) -> Optional[PortalUser]:
        normalized = _validate_email(email)
        for row in self._load():
            if row["email"] == normalized:
                return self._row_to_user(row)
        return None

    def bootstrap_admin(self, *, email: str, password: str, display_name: str) -> PortalUser:
        if self.has_users():
            raise ValueError("bootstrap already completed")
        return self._create(
            email=email,
            password=password,
            display_name=display_name,
            role="admin",
            auth_provider="local",
        )

    def create_local_user(
        self,
        *,
        email: str,
        password: str,
        display_name: str,
        role: Role = "member",
    ) -> PortalUser:
        if self.get_by_email(email):
            raise ValueError("email already registered")
        return self._create(
            email=email,
            password=password,
            display_name=display_name,
            role=role,
            auth_provider="local",
        )

    def authenticate_local(self, *, email: str, password: str) -> Optional[PortalUser]:
        normalized = _validate_email(email)
        for row in self._load():
            if row["email"] != normalized or row.get("auth_provider", "local") != "local":
                continue
            if row.get("password_hash") and _verify_password(row["password_hash"], password):
                row["last_login_at"] = _now_iso()
                self._write(self._load_raw_replace(row))
                return self._row_to_user(row)
        return None

    def upsert_oidc_user(
        self,
        *,
        email: str,
        display_name: str,
        external_subject: str,
        external_issuer: str,
        role: Role = "member",
    ) -> PortalUser:
        """SSO hook — find by external_subject or create."""
        for row in self._load():
            if (
                row.get("external_subject") == external_subject
                and row.get("external_issuer") == external_issuer
            ):
                row["last_login_at"] = _now_iso()
                self._write(self._load_raw_replace(row))
                return self._row_to_user(row)
        return self._create(
            email=email,
            password=None,
            display_name=display_name,
            role=role,
            auth_provider="oidc",
            external_subject=external_subject,
            external_issuer=external_issuer,
        )

    def _create(
        self,
        *,
        email: str,
        password: Optional[str],
        display_name: str,
        role: Role,
        auth_provider: AuthProvider,
        external_subject: Optional[str] = None,
        external_issuer: Optional[str] = None,
    ) -> PortalUser:
        normalized = _validate_email(email)
        name = display_name.strip() or normalized.split("@")[0]
        if not name:
            raise ValueError("display_name is required")
        row = {
            "id": uuid.uuid4().hex[:12],
            "email": normalized,
            "password_hash": _hash_password(password) if password else None,
            "display_name": name[:120],
            "role": role,
            "auth_provider": auth_provider,
            "external_subject": external_subject,
            "external_issuer": external_issuer,
            "created_at": _now_iso(),
            "last_login_at": _now_iso(),
        }
        rows = self._load()
        rows.append(row)
        self._write(rows)
        return self._row_to_user(row)

    def _load_raw_replace(self, updated: dict[str, Any]) -> list[dict[str, Any]]:
        rows = self._load()
        return [updated if r["id"] == updated["id"] else r for r in rows]

    def _load(self) -> list[dict[str, Any]]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, rows: list[dict[str, Any]]) -> None:
        self.path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    def _row_to_user(self, row: dict[str, Any]) -> PortalUser:
        return PortalUser(
            id=row["id"],
            email=row["email"],
            display_name=row["display_name"],
            role=row.get("role", "member"),
            auth_provider=row.get("auth_provider", "local"),
            external_subject=row.get("external_subject"),
            external_issuer=row.get("external_issuer"),
        )


class PostgresUserStore:
    def __init__(self, settings: Settings):
        if not settings.database_url:
            raise ValueError("DATABASE_URL is required")
        self.session_factory = get_session_factory(settings.database_url)

    def has_users(self) -> bool:
        with self.session_factory() as session:
            return session.query(UserRow).count() > 0

    def get_by_id(self, user_id: str) -> Optional[PortalUser]:
        with self.session_factory() as session:
            row = session.get(UserRow, user_id)
            return self._row_to_user(row) if row else None

    def get_by_email(self, email: str) -> Optional[PortalUser]:
        normalized = _validate_email(email)
        with self.session_factory() as session:
            row = session.query(UserRow).filter(UserRow.email == normalized).one_or_none()
            return self._row_to_user(row) if row else None

    def bootstrap_admin(self, *, email: str, password: str, display_name: str) -> PortalUser:
        if self.has_users():
            raise ValueError("bootstrap already completed")
        return self._create(
            email=email,
            password=password,
            display_name=display_name,
            role="admin",
            auth_provider="local",
        )

    def create_local_user(
        self,
        *,
        email: str,
        password: str,
        display_name: str,
        role: Role = "member",
    ) -> PortalUser:
        if self.get_by_email(email):
            raise ValueError("email already registered")
        return self._create(
            email=email,
            password=password,
            display_name=display_name,
            role=role,
            auth_provider="local",
        )

    def authenticate_local(self, *, email: str, password: str) -> Optional[PortalUser]:
        normalized = _validate_email(email)
        with self.session_factory() as session:
            row = session.query(UserRow).filter(UserRow.email == normalized).one_or_none()
            if row is None or row.auth_provider != "local" or not row.password_hash:
                return None
            if not _verify_password(row.password_hash, password):
                return None
            row.last_login_at = utcnow()
            session.commit()
            return self._row_to_user(row)

    def upsert_oidc_user(
        self,
        *,
        email: str,
        display_name: str,
        external_subject: str,
        external_issuer: str,
        role: Role = "member",
    ) -> PortalUser:
        with self.session_factory() as session:
            row = (
                session.query(UserRow)
                .filter(
                    UserRow.external_subject == external_subject,
                    UserRow.external_issuer == external_issuer,
                )
                .one_or_none()
            )
            if row:
                row.last_login_at = utcnow()
                session.commit()
                return self._row_to_user(row)
        return self._create(
            email=email,
            password=None,
            display_name=display_name,
            role=role,
            auth_provider="oidc",
            external_subject=external_subject,
            external_issuer=external_issuer,
        )

    def _create(
        self,
        *,
        email: str,
        password: Optional[str],
        display_name: str,
        role: Role,
        auth_provider: AuthProvider,
        external_subject: Optional[str] = None,
        external_issuer: Optional[str] = None,
    ) -> PortalUser:
        normalized = _validate_email(email)
        name = display_name.strip() or normalized.split("@")[0]
        now = utcnow()
        row = UserRow(
            id=uuid.uuid4().hex[:12],
            email=normalized,
            password_hash=_hash_password(password) if password else None,
            display_name=name[:120],
            role=role,
            auth_provider=auth_provider,
            external_subject=external_subject,
            external_issuer=external_issuer,
            created_at=now,
            last_login_at=now,
        )
        with self.session_factory() as session:
            session.add(row)
            session.commit()
        return self._row_to_user(row)

    def _row_to_user(self, row: UserRow) -> PortalUser:
        return PortalUser(
            id=row.id,
            email=row.email,
            display_name=row.display_name,
            role=row.role,  # type: ignore[arg-type]
            auth_provider=row.auth_provider,  # type: ignore[arg-type]
            external_subject=row.external_subject,
            external_issuer=row.external_issuer,
        )


UserStore = JsonUserStore | PostgresUserStore


def get_user_store(settings: Settings) -> UserStore:
    if postgres_available(settings.database_url):
        return PostgresUserStore(settings)
    return JsonUserStore(settings)
