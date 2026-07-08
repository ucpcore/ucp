"""Tests for portal login, bootstrap, sessions, and SSO stubs."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ucp_server.app import create_app
from ucp_server.token_store import TOKEN_PREFIX

from .conftest import make_settings


@pytest.fixture()
def client(tmp_path, offline):
    settings = make_settings(
        tmp_path,
        UCP_SERVER_API_KEY="admin-secret",
        UCP_SESSION_SECRET="test-session-secret",
        UCP_ALLOW_SELF_SERVICE_TOKENS="1",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client, settings


def test_bootstrap_admin_and_session(client):
    test_client, _ = client
    assert test_client.get("/v1/auth/bootstrap-available").json()["bootstrap"] is True

    created = test_client.post(
        "/v1/auth/bootstrap",
        json={
            "email": "admin@example.com",
            "password": "adminpass1",
            "display_name": "Admin",
        },
    )
    assert created.status_code == 200
    user = created.json()["user"]
    assert user["role"] == "admin"
    assert user["auth_provider"] == "local"
    assert "ucp_portal_session" in created.cookies

    me = test_client.get("/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "admin@example.com"
    assert me.json()["allow_self_service_tokens"] is True

    assert test_client.get("/v1/auth/bootstrap-available").json()["bootstrap"] is False

    dup = test_client.post(
        "/v1/auth/bootstrap",
        json={"email": "other@example.com", "password": "otherpass1"},
    )
    assert dup.status_code == 400


def test_login_logout(client):
    test_client, _ = client
    test_client.post(
        "/v1/auth/bootstrap",
        json={"email": "alice@example.com", "password": "alicepass1"},
    )
    test_client.post("/v1/auth/logout")

    bad = test_client.post(
        "/v1/auth/login",
        json={"email": "alice@example.com", "password": "wrong"},
    )
    assert bad.status_code == 401

    ok = test_client.post(
        "/v1/auth/login",
        json={"email": "alice@example.com", "password": "alicepass1"},
    )
    assert ok.status_code == 200
    assert ok.json()["user"]["email"] == "alice@example.com"

    test_client.post("/v1/auth/logout")
    assert test_client.get("/v1/auth/me").status_code == 401


def test_portal_session_issues_tokens(client):
    test_client, _ = client
    test_client.post(
        "/v1/auth/bootstrap",
        json={"email": "tok@example.com", "password": "tokpass123"},
    )

    created = test_client.post("/v1/me/tokens", json={"name": "mcp"})
    assert created.status_code == 200
    secret = created.json()["secret"]
    assert secret.startswith(TOKEN_PREFIX)

    profile = test_client.get(
        "/v1/me/profile",
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert profile.status_code == 200


def test_token_bootstrap_blocked_when_users_exist(client):
    test_client, _ = client
    test_client.post(
        "/v1/auth/bootstrap",
        json={"email": "admin@example.com", "password": "adminpass1"},
    )
    test_client.post("/v1/auth/logout")

    resp = test_client.post("/v1/me/tokens", json={"name": "anon"})
    assert resp.status_code == 401


def test_oidc_stubs(client):
    test_client, _ = client
    providers = test_client.get("/v1/auth/oidc/providers").json()
    assert providers["configured"] is False
    assert providers["providers"] == []

    start = test_client.get("/v1/auth/oidc/default/start")
    assert start.status_code == 501

    callback = test_client.get("/v1/auth/oidc/default/callback")
    assert callback.status_code == 400


def test_oidc_providers_when_configured(tmp_path, offline):
    settings = make_settings(
        tmp_path,
        UCP_SERVER_API_KEY="k",
        UCP_OIDC_ISSUER="https://idp.example.com",
        UCP_OIDC_CLIENT_ID="client-id",
    )
    with TestClient(create_app(settings)) as test_client:
        providers = test_client.get("/v1/auth/oidc/providers").json()
        assert providers["configured"] is True
        assert len(providers["providers"]) == 1
        assert providers["providers"][0]["id"] == "default"
