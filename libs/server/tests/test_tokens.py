"""Tests for personal API tokens (alpha.12.1)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ucp_server.app import create_app
from ucp_server.token_store import TOKEN_PREFIX, get_token_store

from .conftest import make_settings


@pytest.fixture()
def secured_admin(tmp_path, offline):
    settings = make_settings(tmp_path, UCP_SERVER_API_KEY="admin-secret")
    with TestClient(create_app(settings)) as client:
        yield client, settings


def _admin_headers() -> dict[str, str]:
    return {"Authorization": "Bearer admin-secret"}


def test_create_token_returns_secret_once(secured_admin):
    client, settings = secured_admin
    resp = client.post(
        "/v1/admin/tokens",
        json={"name": "alice", "scopes": ["generate", "receipt"]},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["token"]["name"] == "alice"
    assert data["secret"].startswith(TOKEN_PREFIX)
    assert "generate" in data["token"]["scopes"]

    listed = client.get("/v1/admin/tokens", headers=_admin_headers()).json()
    assert len(listed["tokens"]) == 1
    assert "secret" not in listed["tokens"][0]


def test_personal_token_auth_and_scope(secured_admin):
    client, settings = secured_admin
    created = client.post(
        "/v1/admin/tokens",
        json={"name": "bob", "scopes": ["generate"]},
        headers=_admin_headers(),
    ).json()
    secret = created["secret"]

    ok = client.get("/v1/packages", headers={"Authorization": f"Bearer {secret}"})
    assert ok.status_code == 200

    denied = client.post(
        "/v1/receipt",
        json={
            "package_id": "missing",
            "outcome": "success",
            "claims_cited": [],
            "claims_ignored": [],
        },
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert denied.status_code == 403


def test_personal_token_sets_audience_on_generate(secured_admin):
    client, settings = secured_admin
    secret = client.post(
        "/v1/admin/tokens",
        json={"name": "carol", "scopes": ["generate"]},
        headers=_admin_headers(),
    ).json()["secret"]

    resp = client.post(
        "/v1/generate",
        json={"source": "github", "ref": "acme/rocket#42", "audience": "spoofed"},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 200
    assert resp.json()["audience"]["principal"]["id"] == "carol"


def test_revoke_token(secured_admin):
    client, settings = secured_admin
    created = client.post(
        "/v1/admin/tokens",
        json={"name": "dave", "scopes": ["generate"]},
        headers=_admin_headers(),
    ).json()
    token_id = created["token"]["id"]
    secret = created["secret"]

    assert client.delete(f"/v1/admin/tokens/{token_id}", headers=_admin_headers()).status_code == 200
    assert client.get("/v1/packages", headers={"Authorization": f"Bearer {secret}"}).status_code == 401


def test_token_crud_requires_service_key(secured_admin):
    client, settings = secured_admin
    secret = client.post(
        "/v1/admin/tokens",
        json={"name": "eve", "scopes": ["generate", "admin:read"]},
        headers=_admin_headers(),
    ).json()["secret"]

    resp = client.post(
        "/v1/admin/tokens",
        json={"name": "mallory", "scopes": ["generate"]},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 403


def test_access_log_records_personal_token(secured_admin):
    client, settings = secured_admin
    secret = client.post(
        "/v1/admin/tokens",
        json={"name": "frank", "scopes": ["generate"]},
        headers=_admin_headers(),
    ).json()["secret"]

    client.get("/v1/packages", headers={"Authorization": f"Bearer {secret}"})
    log = client.get("/v1/admin/access-log", headers=_admin_headers()).json()
    assert any(e["principal"] == "frank" for e in log["entries"])


def test_tokens_without_api_key_enable_auth(tmp_path, offline):
    settings = make_settings(tmp_path)
    store = get_token_store(settings)
    _, raw = store.create(name="solo", scopes=["generate"])

    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/packages").status_code == 401
        assert client.get("/v1/packages", headers={"Authorization": f"Bearer {raw}"}).status_code == 200
