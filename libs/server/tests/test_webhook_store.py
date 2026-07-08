"""Webhook endpoint store."""
import pytest

from ucp_server.webhook_store import WebhookEndpointStore


@pytest.fixture()
def store(tmp_path):
    settings = type("S", (), {"cache_dir": tmp_path, "database_url": None, "host": "127.0.0.1", "port": 8080, "public_base_url": None, "tenant_slug": None})()
    return WebhookEndpointStore(settings)


def test_create_and_resolve(store):
    created = store.create(user_id="u1", source="jira", label="My Jira")
    token = created.inbound_url.rsplit("/", 1)[-1]
    resolved = store.resolve("jira", token)
    assert resolved is not None
    endpoint, secret = resolved
    assert endpoint.id == created.endpoint.id
    assert secret == created.signing_secret


def test_revoke_invalidates_token(store):
    created = store.create(user_id="u1", source="confluence")
    token = created.inbound_url.rsplit("/", 1)[-1]
    assert store.revoke(created.endpoint.id, user_id="u1")
    assert store.resolve("confluence", token) is None


def test_list_for_user(store):
    store.create(user_id="u1", source="github")
    store.create(user_id="u2", source="jira")
    assert len(store.list_for_user("u1")) == 1
