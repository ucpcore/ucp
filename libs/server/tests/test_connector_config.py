"""Connector config and /v1/me/connectors API."""
from ucp_server.connector_config import CONNECTOR_SPECS, list_connectors, update_scope

from .conftest import make_settings


def test_list_connectors_without_db(settings):
    data = list_connectors(settings)
    assert len(data["connectors"]) == len(CONNECTOR_SPECS)
    github = next(c for c in data["connectors"] if c["provider"] == "github")
    assert github["label"] == "GitHub"
    assert github["scope_fields"]
    assert github["connected"] is False


def test_update_scope_requires_database(settings):
    try:
        update_scope(settings, "github", {"repos": "acme/app"})
    except RuntimeError as exc:
        assert "DATABASE_URL" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def _portal_client(tmp_path, offline):
    from fastapi.testclient import TestClient

    from ucp_server.app import create_app

    settings = make_settings(
        tmp_path,
        UCP_SERVER_API_KEY="admin-secret",
        UCP_SESSION_SECRET="test-session-secret",
        UCP_ALLOW_SELF_SERVICE_TOKENS="1",
    )
    test_client = TestClient(create_app(settings))
    test_client.post(
        "/v1/auth/bootstrap",
        json={
            "email": "admin@example.com",
            "password": "adminpass1",
            "display_name": "Admin",
        },
    )
    return test_client


def test_me_connectors_endpoint(tmp_path, offline):
    test_client = _portal_client(tmp_path, offline)
    resp = test_client.get("/v1/me/connectors")
    assert resp.status_code == 200
    body = resp.json()
    assert "connectors" in body
    assert any(c["provider"] == "jira" for c in body["connectors"])


def test_me_update_connector_scope_without_db(tmp_path, offline):
    test_client = _portal_client(tmp_path, offline)
    resp = test_client.put(
        "/v1/me/connectors/github/scope",
        json={"scope": {"repos": "acme/rocket"}},
    )
    assert resp.status_code == 503
