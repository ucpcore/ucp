import copy

import pytest
from fastapi.testclient import TestClient

import ucp_server.service as service_module
from ucp_server.app import create_app
from ucp_server.config import Settings

from .fixtures import GITHUB_BUNDLE, JIRA_BUNDLE


@pytest.fixture()
def offline(monkeypatch):
    """Replace ucp-gen network clients with fixture bundles (no sockets)."""

    def fake_github(owner, repo, number, token=None):
        if (owner, repo, number) != ("acme", "rocket", 42):
            raise service_module.GitHubError(f"not found: /repos/{owner}/{repo}/issues/{number}")
        return copy.deepcopy(GITHUB_BUNDLE)

    def fake_jira(key, base_url=None, email=None, token=None):
        if key != "PAY-7":
            raise service_module.JiraError(f"not found: /rest/api/2/issue/{key}")
        return copy.deepcopy(JIRA_BUNDLE)

    monkeypatch.setattr(service_module, "fetch_github", fake_github)
    monkeypatch.setattr(service_module, "fetch_jira", fake_jira)


def make_settings(tmp_path, **overrides) -> Settings:
    defaults = dict(
        UCP_CACHE_DIR=str(tmp_path / "cache"),
        UCP_CACHE_TTL=900,
        UCP_SERVER_HOST="127.0.0.1",
    )
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.fixture()
def settings(tmp_path):
    return make_settings(tmp_path)


@pytest.fixture()
def client(settings, offline):
    with TestClient(create_app(settings)) as test_client:
        yield test_client
