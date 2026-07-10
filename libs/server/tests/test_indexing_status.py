"""Indexing status API."""
from .test_connector_config import _portal_client


def test_me_indexing_status_endpoint(tmp_path, offline, monkeypatch):
    monkeypatch.setattr(
        "ucp_server.app.get_indexing_status",
        lambda settings: {
            "overall_percent": 44,
            "status": "syncing",
            "sources": [
                {
                    "provider": "github",
                    "source": "github",
                    "label": "GitHub",
                    "overall_percent": 44,
                    "status": "syncing",
                    "scopes": [
                        {
                            "scope": "acme/app",
                            "status": "syncing",
                            "percent": 44,
                            "indexed_entities": 3,
                            "batch_indexed": 2,
                            "batch_total": 5,
                        }
                    ],
                }
            ],
        },
    )
    test_client = _portal_client(tmp_path, offline)
    resp = test_client.get("/v1/me/indexing/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall_percent"] == 44
    assert body["sources"][0]["scopes"][0]["percent"] == 44
