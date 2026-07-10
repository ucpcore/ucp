"""Per-user tenant slug in setup payload."""
from __future__ import annotations

from fastapi.testclient import TestClient

from ucp_server.app import create_app
from ucp_server.tenant_resolve import build_setup_for_request

from .conftest import make_settings


def test_setup_uses_user_tenant_slug(tmp_path, offline):
    settings = make_settings(
        tmp_path,
        UCP_MULTI_TENANT="1",
        UCP_TENANT_SLUG="pilot",
        UCP_PUBLIC_BASE_URL="http://api.test",
        UCP_API_PUBLIC_BASE_URL="http://api.test",
    )
    with TestClient(create_app(settings)) as client:
        boot = client.post(
            "/v1/auth/register",
            json={
                "email": "owner@acme.test",
                "password": "securepass1",
                "org_name": "Acme",
                "org_slug": "acme",
            },
        )
        assert boot.status_code == 200

        setup = client.get("/setup?format=json")
        assert setup.status_code == 200
        body = setup.json()
        assert body["tenant_slug"] == "acme"
        assert body["mcp_url"] == "http://api.test/v1/acme/mcp"


def test_build_setup_without_session_falls_back_to_env_slug(tmp_path, offline):
    settings = make_settings(
        tmp_path,
        UCP_TENANT_SLUG="pilot",
        UCP_PUBLIC_BASE_URL="https://api.test",
    )
    payload = build_setup_for_request(settings, request=None)
    assert payload["tenant_slug"] == "pilot"
    assert "pilot" in payload["mcp_url"]
