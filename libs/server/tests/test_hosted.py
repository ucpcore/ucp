"""Tests for hosted pilot tenant paths (RFC-0009)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ucp_server.app import create_app
from ucp_server.tenant import normalize_tenant_slug, rewrite_tenant_path

from .conftest import make_settings


def test_normalize_tenant_slug():
    assert normalize_tenant_slug("Acme-Corp") == "acme-corp"
    with pytest.raises(ValueError):
        normalize_tenant_slug("-bad")


def test_rewrite_paths():
    assert rewrite_tenant_path("/v1/acme/mcp", "acme") == "/mcp"
    assert rewrite_tenant_path("/v1/acme/generate", "acme") == "/v1/generate"
    assert rewrite_tenant_path("/v1/acme/v1/packages", "acme") == "/v1/packages"
    assert rewrite_tenant_path("/v1/acme/admin", "acme") == "/admin"
    assert rewrite_tenant_path("/v1/other/mcp", "acme") is None


@pytest.fixture()
def hosted_client(tmp_path, offline):
    settings = make_settings(
        tmp_path,
        UCP_SERVER_API_KEY="svc",
        UCP_TENANT_SLUG="acme",
        UCP_PUBLIC_BASE_URL="https://mcp.test",
        UCP_HOSTED_MODE="1",
    )
    with TestClient(create_app(settings)) as client:
        yield client


def test_hosted_landing_and_setup(hosted_client):
    landing = hosted_client.get("/")
    assert landing.status_code == 200
    assert "https://mcp.test/v1/acme/mcp" in landing.text

    setup = hosted_client.get("/setup?format=json").json()
    assert setup["mcp_url"] == "https://mcp.test/v1/acme/mcp"
    assert "rangor" in setup["cursor_config"]["mcpServers"]
    assert "claude_code" in setup["client_configs"]
    assert setup["client_configs"]["claude_code"]["config"]["mcpServers"]["rangor"]["type"] == "http"
    assert "headers" not in setup["client_configs"]["claude_code"]["config"]["mcpServers"]["rangor"]
    assert "servers" in setup["client_configs"]["vscode"]["config"]
    assert setup["client_configs"]["vscode"]["config"]["servers"]["rangor"]["type"] == "http"
    assert setup["client_configs"]["cursor"]["config"]["mcpServers"]["rangor"]["icon"] == "https://app.rangor.io/brand/mark.svg"
    assert setup["api_base"] == "/v1/acme"

    setup_html = hosted_client.get("/setup", follow_redirects=False)
    assert setup_html.status_code == 302
    assert setup_html.headers["location"] == "/dashboard/setup"


def test_tenant_mcp_path(hosted_client):
    resp = hosted_client.get(
        "/v1/acme/mcp",
        headers={"Authorization": "Bearer svc"},
    )
    # MCP endpoint may return 405/406 for GET; not 404
    assert resp.status_code != 404


def test_legacy_mcp_blocked_in_hosted_mode(hosted_client):
    resp = hosted_client.get("/mcp", headers={"Authorization": "Bearer svc"})
    assert resp.status_code == 404
    assert resp.json()["title"] == "Hosted API Relocated"


def test_tenant_generate(hosted_client):
    resp = hosted_client.post(
        "/v1/acme/generate",
        json={"source": "github", "ref": "acme/rocket#42"},
        headers={"Authorization": "Bearer svc"},
    )
    assert resp.status_code == 200


def test_health_stays_at_root(hosted_client):
    assert hosted_client.get("/healthz").status_code == 200


def test_local_landing_without_tenant(tmp_path, offline):
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        landing = client.get("/")
        assert landing.status_code == 200
        assert "Rangor MCP" in landing.text
        assert client.get("/setup?format=json").status_code == 200
        html = client.get("/setup", follow_redirects=False)
        assert html.status_code == 302
        assert html.headers["location"] == "/dashboard/setup"
