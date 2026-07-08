"""Connected devices: token metadata, user-scoped list/revoke."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ucp_server.app import create_app
from ucp_server.token_store import TOKEN_PREFIX, get_token_store

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


def _bootstrap(test_client: TestClient) -> None:
    test_client.post(
        "/v1/auth/bootstrap",
        json={"email": "dev@example.com", "password": "devpass123", "display_name": "Dev"},
    )


def test_dashboard_token_has_device_metadata(client):
    test_client, _ = client
    _bootstrap(test_client)

    created = test_client.post("/v1/me/tokens", json={})
    assert created.status_code == 200
    token = created.json()["token"]
    assert token["client_label"] == "Dashboard"
    assert token["auth_method"] == "manual"
    assert token["user_id"] is not None


def test_list_and_revoke_by_user_id(client):
    test_client, settings = client
    _bootstrap(test_client)

    created = test_client.post("/v1/me/tokens", json={})
    secret = created.json()["secret"]
    token_id = created.json()["token"]["id"]

    listed = test_client.get("/v1/me/tokens")
    assert listed.status_code == 200
    tokens = listed.json()["tokens"]
    assert len(tokens) == 1
    assert tokens[0]["id"] == token_id
    assert tokens[0]["client_label"] == "Dashboard"

    store = get_token_store(settings)
    store.resolve(secret)

    refreshed = test_client.get("/v1/me/tokens").json()["tokens"]
    assert refreshed[0]["last_used_at"] is not None

    revoked = test_client.delete(f"/v1/me/tokens/{token_id}")
    assert revoked.status_code == 200
    assert test_client.get("/v1/me/tokens").json()["tokens"] == []


def test_bearer_lists_same_user_devices(client):
    test_client, _ = client
    _bootstrap(test_client)

    first = test_client.post("/v1/me/tokens", json={})
    secret = first.json()["secret"]

    second = test_client.post(
        "/v1/me/tokens",
        json={},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert second.status_code == 200
    assert second.json()["token"]["client_label"] == "Dashboard"

    listed = test_client.get(
        "/v1/me/tokens",
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert listed.status_code == 200
    assert len(listed.json()["tokens"]) == 2


def test_legacy_token_label_from_name(client):
    test_client, settings = client
    _bootstrap(test_client)
    store = get_token_store(settings)
    _, raw = store.create(name="Dev (Cursor)", scopes=["generate", "receipt"])

    listed = test_client.get("/v1/me/tokens").json()["tokens"]
    legacy = next(t for t in listed if t.get("client_label") == "Cursor")
    assert legacy["auth_method"] == "manual"

    assert store.resolve(raw) is not None
