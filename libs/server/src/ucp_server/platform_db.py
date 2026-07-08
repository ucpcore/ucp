"""Platform tables in Postgres: tokens, usage quotas, HTTP audit, OAuth credentials."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

_engine = None
_Session: Optional[sessionmaker] = None


class Base(DeclarativeBase):
    pass


class PersonalTokenRow(Base):
    __tablename__ = "platform_personal_tokens"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(16), index=True, nullable=True)
    client_label: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    auth_method: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    scopes: Mapped[str] = mapped_column(Text)
    secret_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class PrincipalUsageRow(Base):
    __tablename__ = "platform_principal_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    principal: Mapped[str] = mapped_column(String(120), index=True)
    period_key: Mapped[str] = mapped_column(String(7), index=True)
    packages_used: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("principal", "period_key", name="uq_principal_period"),)


class HttpAccessLogRow(Base):
    __tablename__ = "platform_http_access_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    principal: Mapped[str] = mapped_column(String(120), index=True)
    method: Mapped[str] = mapped_column(String(16))
    path: Mapped[str] = mapped_column(String(512))
    status: Mapped[int] = mapped_column(Integer)
    token_id: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    channel: Mapped[str] = mapped_column(String(16), default="rest")


class ConnectorCredentialRow(Base):
    __tablename__ = "platform_connector_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), unique=True)
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InviteRow(Base):
    __tablename__ = "platform_invites"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    principal_name: Mapped[str] = mapped_column(String(120), index=True)
    scopes: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    redeemed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    redeemed_token_id: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    redeemed_user_id: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class UserRow(Base):
    __tablename__ = "platform_users"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(16), default="member")
    auth_provider: Mapped[str] = mapped_column(String(16), default="local")
    external_subject: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    external_issuer: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class WebhookEndpointRow(Base):
    __tablename__ = "platform_webhook_endpoints"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(16), index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)
    label: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    signing_secret: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def bind_database(database_url: str) -> sessionmaker:
    global _engine, _Session
    if _Session is not None:
        return _Session
    _engine = create_engine(database_url, pool_pre_ping=True)
    Base.metadata.create_all(_engine)
    _ensure_personal_token_columns(_engine)
    _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _Session


def _ensure_personal_token_columns(engine) -> None:
    """Additive migration for pilot stacks created before device metadata."""
    stmts = (
        "ALTER TABLE platform_personal_tokens ADD COLUMN IF NOT EXISTS user_id VARCHAR(16)",
        "ALTER TABLE platform_personal_tokens ADD COLUMN IF NOT EXISTS client_label VARCHAR(64)",
        "ALTER TABLE platform_personal_tokens ADD COLUMN IF NOT EXISTS auth_method VARCHAR(16)",
        "CREATE INDEX IF NOT EXISTS ix_platform_personal_tokens_user_id ON platform_personal_tokens (user_id)",
    )
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))


def get_session_factory(database_url: str) -> sessionmaker:
    return bind_database(database_url)


def postgres_available(database_url: Optional[str]) -> bool:
    return bool(database_url and database_url.strip())


def reset_for_tests() -> None:
    global _engine, _Session
    _engine = None
    _Session = None
