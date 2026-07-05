from pathlib import Path

import pytest

from ucp_server.config import ConfigError, Settings, load_settings


def test_defaults_are_safe(monkeypatch):
    for variable in (
        "UCP_SERVER_HOST", "UCP_SERVER_PORT", "UCP_SERVER_API_KEY",
        "UCP_CACHE_DIR", "UCP_CACHE_TTL", "UCP_LOG_JSON", "UCP_LOG_LEVEL",
    ):
        monkeypatch.delenv(variable, raising=False)
    settings = load_settings()
    assert settings.host == "127.0.0.1"  # localhost by default: exposing is opt-in
    assert settings.port == 8080
    assert settings.api_key is None
    assert settings.cache_ttl == 900
    assert settings.log_json is False


def test_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("UCP_SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("UCP_SERVER_PORT", "9000")
    monkeypatch.setenv("UCP_SERVER_API_KEY", "k")
    monkeypatch.setenv("UCP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("UCP_CACHE_TTL", "0")
    monkeypatch.setenv("UCP_LOG_JSON", "true")
    settings = load_settings()
    assert settings.host == "0.0.0.0"
    assert settings.port == 9000
    assert settings.api_key == "k"
    assert settings.cache_dir == tmp_path
    assert settings.cache_ttl == 0
    assert settings.log_json is True


def test_cache_dir_expands_user():
    settings = Settings(UCP_CACHE_DIR="~/somewhere")
    assert settings.cache_dir == Path.home() / "somewhere"


def test_invalid_value_gives_readable_error(monkeypatch):
    monkeypatch.setenv("UCP_CACHE_TTL", "fifteen minutes")
    with pytest.raises(ConfigError) as excinfo:
        load_settings()
    message = str(excinfo.value)
    assert "invalid configuration" in message
    assert "UCP_CACHE_TTL" in message  # the env var name, not the internal field name


def test_port_range_is_validated(monkeypatch):
    monkeypatch.setenv("UCP_SERVER_PORT", "70000")
    with pytest.raises(ConfigError):
        load_settings()
