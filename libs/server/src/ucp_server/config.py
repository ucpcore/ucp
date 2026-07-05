"""Server configuration — environment variables only (12-factor).

Every setting is optional with a safe default. Startup fails fast with a
human-readable message when a value cannot be parsed (e.g. a non-numeric
UCP_CACHE_TTL) instead of surfacing a stack trace at request time.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

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
