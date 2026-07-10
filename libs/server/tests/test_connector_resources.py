"""Connector resource listing API."""
import pytest

from ucp_server.connector_resources import list_connector_resources

from .conftest import make_settings
from .test_connector_config import _portal_client


@pytest.mark.asyncio
async def test_github_repos_requires_token(settings):
    with pytest.raises(RuntimeError, match="not connected"):
        await list_connector_resources(settings, "github", "repos")


@pytest.mark.asyncio
async def test_github_repos_parses(monkeypatch, tmp_path):
    settings = make_settings(tmp_path, GITHUB_TOKEN="gh_test")

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return [
                {"full_name": "acme/rocket", "private": False},
                {"full_name": "acme/private", "private": True},
            ]

    async def fake_get(self, url, **kwargs):
        assert "user/repos" in url
        return FakeResp()

    monkeypatch.setattr(
        "ucp_server.connector_resources.httpx.AsyncClient.get",
        fake_get,
    )

    data = await list_connector_resources(settings, "github", "repos")
    assert data["field"] == "repos"
    assert len(data["items"]) == 2
    assert data["items"][0]["value"] == "acme/rocket"
    assert "🔒" in data["items"][1]["label"]


def test_me_connector_resources_endpoint(tmp_path, offline, monkeypatch):
    async def fake_list(settings, provider, field):
        return {
            "provider": provider,
            "field": field,
            "items": [{"value": "KAN", "label": "Kanban (KAN)"}],
        }

    monkeypatch.setattr(
        "ucp_server.app.list_connector_resources",
        fake_list,
    )
    test_client = _portal_client(tmp_path, offline)
    resp = test_client.get("/v1/me/connectors/jira/resources?field=projects")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"][0]["value"] == "KAN"


def test_me_connector_resources_unknown_field(tmp_path, offline):
    test_client = _portal_client(tmp_path, offline)
    resp = test_client.get("/v1/me/connectors/github/resources?field=folders")
    assert resp.status_code == 404
