"""Tests for single-use invite links (account signup flow)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ucp_server.app import create_app
from ucp_server.token_store import TOKEN_PREFIX

from .conftest import make_settings


@pytest.fixture()
def secured_admin(tmp_path, offline):
    settings = make_settings(tmp_path, UCP_SERVER_API_KEY="admin-secret")
    with TestClient(create_app(settings)) as client:
        yield client, settings


def _admin_headers() -> dict[str, str]:
    return {"Authorization": "Bearer admin-secret"}


def test_admin_create_and_register_invite(secured_admin):
    client, settings = secured_admin
    created = client.post(
        "/v1/admin/invites",
        json={"name": "bob", "scopes": ["generate", "receipt"]},
        headers=_admin_headers(),
    )
    assert created.status_code == 200
    body = created.json()
    code = body["code"]
    assert code.startswith("inv_")
    assert "/dashboard/invite?code=" in body["invite_path"]

    preview = client.get(f"/v1/me/invites/preview?code={code}")
    assert preview.status_code == 200
    assert preview.json()["status"] == "pending"
    assert preview.json()["principal_name"] == "bob"

    registered = client.post(
        "/v1/auth/register-invite",
        json={
            "code": code,
            "email": "bob@example.com",
            "password": "securepass1",
            "display_name": "bob",
        },
    )
    assert registered.status_code == 200
    assert registered.json()["user"]["email"] == "bob@example.com"
    assert "ucp_portal_session" in registered.cookies

    profile = client.get("/v1/me/profile")
    assert profile.status_code == 200
    assert profile.json()["principal"] == "bob"
    assert profile.json()["email"] == "bob@example.com"

    token_resp = client.post("/v1/me/tokens", json={"name": "bob-mcp"})
    assert token_resp.status_code == 200
    secret = token_resp.json()["secret"]
    assert secret.startswith(TOKEN_PREFIX)

    again = client.post(
        "/v1/auth/register-invite",
        json={
            "code": code,
            "email": "mallory@example.com",
            "password": "securepass2",
        },
    )
    assert again.status_code == 400

    invites = client.get("/v1/admin/invites", headers=_admin_headers()).json()["invites"]
    assert any(i["principal_name"] == "bob" and i["status"] == "redeemed" for i in invites)


def test_invite_requires_service_key_to_create(secured_admin):
    client, _ = secured_admin
    resp = client.post("/v1/admin/invites", json={"name": "mallory", "scopes": ["generate"]})
    assert resp.status_code == 401


def test_revoke_pending_invite(secured_admin):
    client, _ = secured_admin
    created = client.post(
        "/v1/admin/invites",
        json={"name": "carol", "scopes": ["generate"]},
        headers=_admin_headers(),
    ).json()
    invite_id = created["invite"]["id"]
    code = created["code"]

    assert client.delete(f"/v1/admin/invites/{invite_id}", headers=_admin_headers()).status_code == 200

    preview = client.get(f"/v1/me/invites/preview?code={code}").json()
    assert preview["status"] == "revoked"

    register = client.post(
        "/v1/auth/register-invite",
        json={
            "code": code,
            "email": "carol@example.com",
            "password": "securepass1",
        },
    )
    assert register.status_code == 400


def test_hosted_invite_paths(hosted_client):
    created = hosted_client.post(
        "/v1/acme/v1/admin/invites",
        json={"name": "dave", "scopes": ["generate", "receipt"]},
        headers={"Authorization": "Bearer svc"},
    )
    assert created.status_code == 200
    code = created.json()["code"]
    assert "https://mcp.test/dashboard/invite?code=" in created.json()["invite_url"]

    preview = hosted_client.get(f"/v1/acme/me/invites/preview?code={code}")
    assert preview.status_code == 200

    registered = hosted_client.post(
        "/v1/acme/v1/auth/register-invite",
        json={
            "code": code,
            "email": "dave@example.com",
            "password": "securepass1",
        },
    )
    assert registered.status_code == 200
    assert registered.cookies.get("ucp_portal_session")


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
