"""Billing stub API tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ucp_server.app import create_app

from .conftest import make_settings


@pytest.fixture()
def billing_client(tmp_path, offline):
    settings = make_settings(tmp_path, UCP_SERVER_API_KEY="svc", UCP_CACHE_TTL=0)
    with TestClient(create_app(settings)) as client:
        yield client


def test_plans_public(billing_client):
    resp = billing_client.get("/v1/billing/plans")
    assert resp.status_code == 200
    plans = resp.json()["plans"]
    assert {p["id"] for p in plans} == {"free", "pro"}
    assert resp.json()["stub_mode"] is True


def test_checkout_and_simulate_upgrade(billing_client):
    session = billing_client.post("/v1/billing/checkout", json={"plan": "pro"}).json()
    assert session["id"].startswith("cs_stub_")

    done = billing_client.post(
        "/v1/billing/simulate-payment",
        json={"session_id": session["id"]},
    )
    assert done.status_code == 200
    assert done.json()["subscription"]["plan"] == "pro"

    sub = billing_client.get(
        "/v1/billing/subscription",
        headers={"Authorization": "Bearer svc"},
    ).json()
    assert sub["plan"] == "pro"


def test_quota_on_generate_free_plan(billing_client):
    from ucp_server.token_store import TOKEN_PREFIX
    from ucp_server.usage_store import get_usage_store

    secret = billing_client.post(
        "/v1/me/tokens",
        json={"name": "quota-user"},
    ).json()["secret"]
    assert secret.startswith(TOKEN_PREFIX)
    headers = {"Authorization": f"Bearer {secret}"}

    usage = get_usage_store(billing_client.app.state.settings)
    for _ in range(50):
        billing_client.post(
            "/v1/generate",
            json={"source": "github", "ref": "acme/rocket#42"},
            headers=headers,
        )

    resp = billing_client.post(
        "/v1/generate",
        json={"source": "github", "ref": "acme/rocket#42"},
        headers=headers,
    )
    assert resp.status_code == 429
