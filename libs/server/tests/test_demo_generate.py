"""Tests for public /v1/demo/generate endpoint."""
from __future__ import annotations

import pytest


@pytest.fixture
def demo_client(tmp_path, offline, monkeypatch):
    monkeypatch.setenv("UCP_DEMO_ENABLED", "1")
    monkeypatch.setenv("UCP_CACHE_DIR", str(tmp_path / "cache"))
    from ucp_server.app import create_app
    from ucp_server.config import load_settings

    return __import__("fastapi.testclient").testclient.TestClient(create_app(load_settings()))


def test_demo_disabled_by_default(client):
    resp = client.post("/v1/demo/generate", json={"ref": "acme/demo#1"})
    assert resp.status_code == 404


def test_demo_generate_mocked(demo_client, monkeypatch):
    fake = {
        "package": {
            "ucp_version": "0.1.1",
            "id": "urn:uuid:demo",
            "generated_at": "2026-07-10T12:00:00Z",
            "generator": {"name": "test"},
            "entity": {
                "ref": {"system": "github", "type": "issue", "id": "acme/demo#1"},
                "title": "Demo",
            },
            "summary": {"text": "ok"},
            "sources": {"s1": {"system": "github", "type": "issue", "title": "Demo"}},
        },
        "stats": {
            "ref": "acme/demo#1",
            "raw_tokens": 1000,
            "ucp_tokens": 200,
            "reduction_pct": 80,
        },
    }
    monkeypatch.setattr("ucp_server.app.generate_demo_package", lambda ref, **kw: fake)
    resp = demo_client.post("/v1/demo/generate", json={"ref": "acme/demo#1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["stats"]["ref"] == "acme/demo#1"
    assert body["package"]["summary"]["text"] == "ok"


def test_demo_invalid_ref(demo_client):
    resp = demo_client.post("/v1/demo/generate", json={"ref": "not-a-ref"})
    assert resp.status_code == 400


def test_demo_rate_limit(demo_client, monkeypatch):
    monkeypatch.setattr(
        "ucp_server.app.generate_demo_package",
        lambda ref, **kw: {
            "package": {
                "ucp_version": "0.1.1",
                "id": "urn:uuid:x",
                "generated_at": "2026-07-10T12:00:00Z",
                "generator": {"name": "t"},
                "entity": {
                    "ref": {"system": "github", "type": "issue", "id": "a/b#1"},
                    "title": "t",
                },
                "sources": {"s": {"system": "github", "type": "issue", "title": "t"}},
            },
            "stats": {"ref": "a/b#1", "raw_tokens": 1, "ucp_tokens": 1, "reduction_pct": 0},
        },
    )
    limiter = demo_client.app.state.demo_rate_limiter
    limiter.limit = 2
    for _ in range(2):
        assert demo_client.post("/v1/demo/generate", json={"ref": "a/b#1"}).status_code == 200
    assert demo_client.post("/v1/demo/generate", json={"ref": "a/b#1"}).status_code == 429
