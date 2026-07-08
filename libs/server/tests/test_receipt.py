"""Tests for Usage Receipt store and API."""
from __future__ import annotations

import json

from ucp_server.receipt_store import ReceiptStore

from .conftest import make_settings


def test_receipt_store_append_and_list(tmp_path):
    settings = make_settings(tmp_path)
    store = ReceiptStore(settings)
    store.append(
        {
            "package_id": "jira-kan-7",
            "outcome": "task_completed",
            "claims_cited": ["content"],
            "claims_ignored": [],
            "consumer": {"type": "sidebar", "id": "test"},
        }
    )
    rows = store.list_recent(limit=5)
    assert len(rows) == 1
    assert rows[0]["receipt"]["package_id"] == "jira-kan-7"
    agg = store.aggregate()
    assert agg["total"] == 1
    assert agg["outcomes"]["task_completed"] == 1


def test_submit_receipt_requires_cached_package(client):
    resp = client.post(
        "/v1/receipt",
        json={
            "package_id": "missing-package-id",
            "package_generated_at": "2026-07-08T12:00:00Z",
            "consumer": {"type": "sidebar", "id": "test"},
            "claims_cited": [],
            "claims_ignored": [],
            "outcome": "abandoned",
        },
    )
    assert resp.status_code == 404


def test_submit_receipt_after_generate(client):
    gen = client.post("/v1/generate", json={"source": "github", "ref": "acme/rocket#42"})
    assert gen.status_code == 200
    package_id = gen.headers["X-UCP-Package-Id"]
    generated_at = gen.json()["generated_at"]

    resp = client.post(
        "/v1/receipt",
        json={
            "package_id": package_id,
            "package_generated_at": generated_at,
            "consumer": {"type": "sidebar", "id": "0.3.0-alpha.12"},
            "claims_cited": ["comment-100-gist"],
            "claims_ignored": ["noise"],
            "gaps_needed": [],
            "outcome": "task_completed",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["package_id"] == package_id

    admin = client.get("/v1/admin/receipts?limit=5")
    assert admin.status_code == 200
    data = admin.json()
    assert data["aggregate"]["total"] >= 1
    assert data["receipts"][-1]["receipt"]["package_id"] == package_id
