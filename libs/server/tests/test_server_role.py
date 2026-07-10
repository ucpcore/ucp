"""Server role split and multi-tenant path routing."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ucp_server.app import create_app
from ucp_server.tenant import extract_tenant_slug_from_path

from .conftest import make_settings


def test_extract_tenant_slug_from_path():
    assert extract_tenant_slug_from_path("/v1/acme/mcp") == "acme"
    assert extract_tenant_slug_from_path("/v1/oauth/mcp/start") is None
    assert extract_tenant_slug_from_path("/v1/me/webhooks") is None


def test_api_role_hides_portal(tmp_path, offline):
    settings = make_settings(
        tmp_path,
        UCP_SERVER_ROLE="api",
        UCP_TENANT_SLUG="pilot",
        UCP_PUBLIC_BASE_URL="https://api.test",
        UCP_MULTI_TENANT="1",
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/dashboard").status_code == 404
        assert client.get("/dashboard/setup").status_code == 404


def test_multi_tenant_unknown_slug(tmp_path, offline):
    settings = make_settings(
        tmp_path,
        UCP_SERVER_ROLE="api",
        UCP_TENANT_SLUG="pilot",
        UCP_PUBLIC_BASE_URL="https://api.test",
        UCP_MULTI_TENANT="1",
        UCP_HOSTED_MODE="1",
    )
    with TestClient(create_app(settings)) as client:
        resp = client.get("/v1/unknown-tenant/mcp")
        assert resp.status_code == 404
        assert resp.json()["title"] == "Tenant Not Found"


def test_multi_tenant_bootstrap_default_tenant(tmp_path, offline):
    settings = make_settings(
        tmp_path,
        UCP_SERVER_ROLE="api",
        UCP_TENANT_SLUG="pilot",
        UCP_PUBLIC_BASE_URL="https://api.test",
        UCP_MULTI_TENANT="1",
        UCP_HOSTED_MODE="1",
        UCP_SERVER_API_KEY="svc",
    )
    with TestClient(create_app(settings)) as client:
        resp = client.get(
            "/v1/pilot/mcp",
            headers={"Authorization": "Bearer svc"},
        )
        assert resp.status_code != 404


def test_setup_html_redirects_to_portal_on_api_role(tmp_path, offline):
    settings = make_settings(
        tmp_path,
        UCP_SERVER_ROLE="api",
        UCP_PORTAL_PUBLIC_BASE_URL="https://app.test",
    )
    with TestClient(create_app(settings)) as client:
        resp = client.get("/setup", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "https://app.test/dashboard/setup"
