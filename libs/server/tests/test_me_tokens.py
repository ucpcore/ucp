"""Tests for user self-service tokens (/v1/me/*)."""
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


def test_bootstrap_first_token(secured_admin):
    client, _ = secured_admin
    resp = client.post("/v1/me/tokens", json={"name": "alice"})
    assert resp.status_code == 200
    secret = resp.json()["secret"]
    assert secret.startswith(TOKEN_PREFIX)

    profile = client.get("/v1/me/profile", headers={"Authorization": f"Bearer {secret}"})
    assert profile.status_code == 200
    assert profile.json()["principal"] == "alice"


def test_bootstrap_blocked_when_tokens_exist(secured_admin):
    client, _ = secured_admin
    client.post(
        "/v1/admin/tokens",
        json={"name": "bob", "scopes": ["generate"]},
        headers=_admin_headers(),
    )
    resp = client.post("/v1/me/tokens", json={"name": "mallory"})
    assert resp.status_code == 401


def test_self_service_rotate(secured_admin):
    client, _ = secured_admin
    secret = client.post("/v1/me/tokens", json={"name": "carol"}).json()["secret"]
    headers = {"Authorization": f"Bearer {secret}"}

    rotated = client.post("/v1/me/tokens", json={"rotate": True}, headers=headers)
    assert rotated.status_code == 200
    new_secret = rotated.json()["secret"]
    assert new_secret != secret

    assert client.get("/v1/me/profile", headers=headers).status_code == 401
    assert client.get("/v1/me/profile", headers={"Authorization": f"Bearer {new_secret}"}).status_code == 200


def test_billing_subscription_with_personal_token(secured_admin):
    client, _ = secured_admin
    secret = client.post("/v1/me/tokens", json={"name": "dave"}).json()["secret"]
    resp = client.get("/v1/billing/subscription", headers={"Authorization": f"Bearer {secret}"})
    assert resp.status_code == 200
    assert resp.json()["plan"] == "free"


def test_service_key_rejected_on_me_profile(secured_admin):
    client, _ = secured_admin
    resp = client.get("/v1/me/profile", headers=_admin_headers())
    assert resp.status_code == 403
