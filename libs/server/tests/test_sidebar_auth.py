"""Tests for Chrome Sidebar portal connect flow."""
from __future__ import annotations

from ucp_server.token_store import TOKEN_PREFIX

from .conftest import make_settings


def test_sidebar_connect_requires_login(tmp_path, offline):
    from fastapi.testclient import TestClient
    from ucp_server.app import create_app

    settings = make_settings(
        tmp_path,
        UCP_SESSION_SECRET="test-session-secret",
        UCP_ALLOW_SELF_SERVICE_TOKENS="1",
    )
    with TestClient(create_app(settings)) as test_client:
        resp = test_client.get(
            "/v1/auth/sidebar/connect",
            params={"extension_id": "a" * 32},
        )
        assert resp.status_code == 200
        assert "Войти через Portal" in resp.text


def test_sidebar_connect_issues_token(tmp_path, offline):
    from fastapi.testclient import TestClient
    from ucp_server.app import create_app

    settings = make_settings(
        tmp_path,
        UCP_SESSION_SECRET="test-session-secret",
        UCP_ALLOW_SELF_SERVICE_TOKENS="1",
    )
    with TestClient(create_app(settings)) as test_client:
        test_client.post(
            "/v1/auth/bootstrap",
            json={
                "email": "sidebar@example.com",
                "password": "adminpass1",
                "display_name": "Sidebar User",
            },
        )
        ext_id = "b" * 32
        resp = test_client.get(
            "/v1/auth/sidebar/connect",
            params={"extension_id": ext_id},
        )
        assert resp.status_code == 200
        assert "contextos:sidebar-connected" in resp.text
        assert TOKEN_PREFIX in resp.text
        assert ext_id in resp.text

        listed = test_client.get("/v1/me/tokens").json()["tokens"]
        assert any(t.get("client_label") == "Chrome Sidebar" for t in listed)


def test_setup_payload_includes_sidebar(tmp_path, offline):
    from fastapi.testclient import TestClient
    from ucp_server.app import create_app

    settings = make_settings(
        tmp_path,
        UCP_TENANT_SLUG="pilot",
        UCP_PUBLIC_BASE_URL="https://mcp.example.com",
        UCP_HOSTED_MODE="1",
    )
    with TestClient(create_app(settings)) as test_client:
        payload = test_client.get("/setup?format=json").json()
    assert payload["sidebar"]["mode"] == "hosted"
    assert payload["sidebar"]["api_url"] == "https://mcp.example.com/v1/pilot"
    assert "sidebar/connect" in payload["sidebar"]["connect_url"]
