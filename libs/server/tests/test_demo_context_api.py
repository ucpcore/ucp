"""Indexing status API."""
from .test_connector_config import _portal_client


def test_me_demo_context_endpoint(tmp_path, offline, monkeypatch):
    monkeypatch.setattr(
        "ucp_server.app.build_demo_context",
        lambda settings, principal, cache: {
            "comparison": {"mode": "benchmark", "raw_tokens": 18500, "ucp_tokens": 1200},
            "agents": {"cursor": {"label": "Cursor", "prompt": "/ucp x"}},
        },
    )
    test_client = _portal_client(tmp_path, offline)
    resp = test_client.get("/v1/me/demo-context")
    assert resp.status_code == 200
    assert resp.json()["comparison"]["raw_tokens"] == 18500
