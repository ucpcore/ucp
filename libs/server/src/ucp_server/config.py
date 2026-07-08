"""Server configuration — environment variables only (12-factor).

Every setting is optional with a safe default. Startup fails fast with a
human-readable message when a value cannot be parsed (e.g. a non-numeric
UCP_CACHE_TTL) instead of surfacing a stack trace at request time.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import AliasChoices, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CACHE_TTL = 900  # 15 minutes
MAX_BODY_BYTES = 64 * 1024


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # Bind. 127.0.0.1 by default: exposing the server is an explicit decision
    # (the Docker image sets 0.0.0.0 because the container boundary isolates it).
    host: str = Field(default="127.0.0.1", validation_alias="UCP_SERVER_HOST")
    port: int = Field(default=8080, ge=1, le=65535, validation_alias="UCP_SERVER_PORT")

    # Optional bearer-token auth. When set, every endpoint except
    # /healthz and /readyz requires `Authorization: Bearer <key>`.
    api_key: Optional[str] = Field(default=None, validation_alias="UCP_SERVER_API_KEY")

    # Hosted pilot (RFC-0009): tenant-scoped public URLs on a dedicated VM.
    tenant_slug: Optional[str] = Field(default=None, validation_alias="UCP_TENANT_SLUG")
    public_base_url: Optional[str] = Field(default=None, validation_alias="UCP_PUBLIC_BASE_URL")
    hosted_mode: bool = Field(default=False, validation_alias="UCP_HOSTED_MODE")

    # Disk cache for generated packages. TTL in seconds; 0 disables caching.
    cache_dir: Path = Field(
        default=Path("~/.cache/ucp-server"), validation_alias="UCP_CACHE_DIR"
    )
    cache_ttl: int = Field(
        default=DEFAULT_CACHE_TTL, ge=0, validation_alias="UCP_CACHE_TTL"
    )

    # Upstream credentials (all optional; a source that lacks credentials
    # reports a clear error on use, not at startup).
    github_token: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("GITHUB_TOKEN", "GH_TOKEN")
    )
    jira_base_url: Optional[str] = Field(default=None, validation_alias="JIRA_BASE_URL")
    jira_email: Optional[str] = Field(default=None, validation_alias="JIRA_EMAIL")
    jira_api_token: Optional[str] = Field(default=None, validation_alias="JIRA_API_TOKEN")

    # Context OS engine (stage 1): serve GitHub packages from background index when available.
    engine_enabled: bool = Field(default=False, validation_alias="CONTEXTOS_ENGINE_ENABLED")
    database_url: Optional[str] = Field(default=None, validation_alias="DATABASE_URL")
    neo4j_uri: Optional[str] = Field(default=None, validation_alias="NEO4J_URI")
    neo4j_user: Optional[str] = Field(default=None, validation_alias="NEO4J_USER")
    neo4j_password: Optional[str] = Field(default=None, validation_alias="NEO4J_PASSWORD")
    graph_group_id: str = Field(default="contextos", validation_alias="GRAPH_GROUP_ID")

    spicedb_enabled: bool = Field(default=False, validation_alias="SPICEDB_ENABLED")
    spicedb_grpc_addr: str = Field(default="spicedb:50051", validation_alias="SPICEDB_GRPC_ADDR")
    spicedb_preshared_key: Optional[str] = Field(
        default=None, validation_alias="SPICEDB_PRESHARED_KEY"
    )
    permissions_require_principal: bool = Field(
        default=False, validation_alias="PERMISSIONS_REQUIRE_PRINCIPAL"
    )
    acl_sync_default_viewer: Optional[str] = Field(
        default=None, validation_alias="ACL_SYNC_DEFAULT_VIEWER"
    )
    acl_sync_extra_viewers_csv: str = Field(
        default="", validation_alias="ACL_SYNC_EXTRA_VIEWERS"
    )

    ranking_enabled: bool = Field(default=True, validation_alias="RANKING_ENABLED")
    ranking_top_n: int = Field(default=10, ge=1, le=50, validation_alias="RANKING_TOP_N")
    ranking_warm_enabled: bool = Field(default=True, validation_alias="RANKING_WARM_ENABLED")

    redis_url: Optional[str] = Field(default=None, validation_alias="REDIS_URL")
    github_webhook_secret: Optional[str] = Field(
        default=None, validation_alias="GITHUB_WEBHOOK_SECRET"
    )

    github_oauth_client_id: Optional[str] = Field(
        default=None, validation_alias="GITHUB_OAUTH_CLIENT_ID"
    )
    github_oauth_client_secret: Optional[str] = Field(
        default=None, validation_alias="GITHUB_OAUTH_CLIENT_SECRET"
    )
    atlassian_oauth_client_id: Optional[str] = Field(
        default=None, validation_alias="ATLASSIAN_OAUTH_CLIENT_ID"
    )
    atlassian_oauth_client_secret: Optional[str] = Field(
        default=None, validation_alias="ATLASSIAN_OAUTH_CLIENT_SECRET"
    )

    # Portal accounts (local login + future SSO)
    session_secret: Optional[str] = Field(default=None, validation_alias="UCP_SESSION_SECRET")
    session_ttl_hours: int = Field(default=168, ge=1, le=720, validation_alias="UCP_SESSION_TTL_HOURS")
    allow_self_service_tokens: bool = Field(
        default=True, validation_alias="UCP_ALLOW_SELF_SERVICE_TOKENS"
    )
    oidc_issuer: Optional[str] = Field(default=None, validation_alias="UCP_OIDC_ISSUER")
    oidc_client_id: Optional[str] = Field(default=None, validation_alias="UCP_OIDC_CLIENT_ID")
    oidc_client_secret: Optional[str] = Field(default=None, validation_alias="UCP_OIDC_CLIENT_SECRET")

    # Logging: human-readable by default, JSON when UCP_LOG_JSON=1/true.
    log_json: bool = Field(default=False, validation_alias="UCP_LOG_JSON")
    log_level: str = Field(default="INFO", validation_alias="UCP_LOG_LEVEL")

    @field_validator("cache_dir", mode="after")
    @classmethod
    def _expand(cls, value: Path) -> Path:
        return value.expanduser()

    @field_validator("log_level", mode="after")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()

    @field_validator("tenant_slug", mode="before")
    @classmethod
    def _tenant_slug(cls, value: Any) -> Optional[str]:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        from .tenant import normalize_tenant_slug

        return normalize_tenant_slug(str(value))

    @field_validator("hosted_mode", mode="before")
    @classmethod
    def _hosted_mode(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in {"1", "true", "yes", "on"}


class ConfigError(RuntimeError):
    pass


def load_settings() -> Settings:
    """Load settings from the environment, raising a readable ConfigError."""
    try:
        return Settings()
    except ValidationError as exc:
        lines = ["invalid configuration:"]
        for error in exc.errors():
            variable = ".".join(str(loc) for loc in error["loc"]) or "?"
            lines.append(f"  {variable}: {error['msg']}")
        raise ConfigError("\n".join(lines)) from exc
