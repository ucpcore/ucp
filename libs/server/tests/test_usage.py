"""Tests for per-principal usage quota."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ucp_server.app import create_app
from ucp_server.token_store import TOKEN_PREFIX

from .conftest import make_settings


@pytest.fixture()
def secured(tmp_path, offline):
    settings = make_settings(tmp_path, UCP_SERVER_API_KEY="admin-secret", UCP_CACHE_TTL=0)
    with TestClient(create_app(settings)) as client:
        yield client, settings


def test_quota_per_principal_not_service(secured):
    client, settings = secured
    secret = client.post("/v1/me/tokens", json={"name": "alice"}).json()["secret"]
    headers = {"Authorization": f"Bearer {secret}"}

    from ucp_server.usage_store import get_usage_store

    usage = get_usage_store(settings)
    for _ in range(50):
        resp = client.post(
            "/v1/generate",
            json={"source": "github", "ref": "acme/rocket#42"},
            headers=headers,
        )
        assert resp.status_code == 200

    blocked = client.post(
        "/v1/generate",
        json={"source": "github", "ref": "acme/rocket#42"},
        headers=headers,
    )
    assert blocked.status_code == 429

    # Service key is not quota-limited
    svc = client.post(
        "/v1/generate",
        json={"source": "github", "ref": "acme/rocket#42"},
        headers={"Authorization": "Bearer admin-secret"},
    )
    assert svc.status_code == 200


def test_me_usage_endpoint(secured):
    client, _ = secured
    secret = client.post("/v1/me/tokens", json={"name": "bob"}).json()["secret"]
    headers = {"Authorization": f"Bearer {secret}"}

    client.post(
        "/v1/generate",
        json={"source": "github", "ref": "acme/rocket#42"},
        headers=headers,
    )
    usage = client.get("/v1/me/usage", headers=headers).json()
    assert usage["principal"] == "bob"
    assert usage["packages_used"] >= 1
    assert "daily" in usage
