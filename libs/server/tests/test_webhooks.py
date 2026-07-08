"""GitHub, Jira, and Confluence webhook parsing and handlers."""
import hashlib
import hmac
import json

import pytest

from ucp_server.webhooks import (
    handle_confluence_webhook,
    handle_github_webhook,
    handle_inbound_webhook,
    handle_jira_webhook,
    parse_confluence_webhook,
    parse_github_webhook,
    parse_jira_webhook,
    verify_github_signature,
)


def test_verify_github_signature():
    secret = "test-secret"
    body = b'{"action":"opened"}'
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_github_signature(body, sig, secret)
    assert not verify_github_signature(body, "sha256=bad", secret)


def test_parse_github_issue_opened():
    payload = {
        "action": "opened",
        "issue": {"number": 42},
        "repository": {"full_name": "acme/rocket"},
    }
    assert parse_github_webhook(payload) == ("acme", "rocket", 42)


def test_parse_jira_issue_updated():
    payload = {
        "webhookEvent": "jira:issue_updated",
        "issue": {"key": "kan-7"},
    }
    assert parse_jira_webhook(payload) == "KAN-7"


def test_parse_confluence_page_updated():
    payload = {
        "event": "page_updated",
        "page": {"id": "123456", "spaceKey": "DOCS"},
    }
    assert parse_confluence_webhook(payload) == "DOCS:123456"


def test_handle_github_webhook_queues_task(monkeypatch):
    body = json.dumps(
        {
            "action": "edited",
            "issue": {"number": 7},
            "repository": {"full_name": "acme/demo"},
        }
    ).encode()
    secret = "wh-secret"
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    calls: list[tuple] = []

    def fake_trigger(owner, repo, number, *, redis_url):
        calls.append((owner, repo, number, redis_url))
        return "task-abc"

    monkeypatch.setattr("ucp_server.webhooks.queue_github_issue_index", fake_trigger)
    result = handle_github_webhook(
        body=body, signature=sig, secret=secret, redis_url="redis://localhost/0"
    )
    assert result["status"] == "queued"
    assert result["task_id"] == "task-abc"
    assert calls == [("acme", "demo", 7, "redis://localhost/0")]


def test_handle_jira_webhook_queues_task(monkeypatch):
    body = json.dumps(
        {"webhookEvent": "jira:issue_updated", "issue": {"key": "PAY-7"}}
    ).encode()

    def fake_trigger(key, *, redis_url):
        assert key == "PAY-7"
        return "jira-task"

    monkeypatch.setattr("ucp_server.webhooks.queue_jira_issue_index", fake_trigger)
    result = handle_jira_webhook(
        body=body, secret=None, configured_secret=None, redis_url="redis://localhost/0"
    )
    assert result["issue_key"] == "PAY-7"
    assert result["task_id"] == "jira-task"


def test_handle_confluence_webhook_queues_task(monkeypatch):
    body = json.dumps(
        {"event": "page_updated", "page": {"id": 99, "spaceKey": "ENG"}}
    ).encode()

    def fake_trigger(external_id, *, redis_url):
        assert external_id == "ENG:99"
        return "cf-task"

    monkeypatch.setattr("ucp_server.webhooks.queue_confluence_page_index", fake_trigger)
    result = handle_confluence_webhook(
        body=body, secret=None, configured_secret=None, redis_url="redis://localhost/0"
    )
    assert result["page"] == "ENG:99"


def test_handle_inbound_webhook_github(monkeypatch):
    body = json.dumps(
        {
            "action": "opened",
            "issue": {"number": 1},
            "repository": {"full_name": "o/r"},
        }
    ).encode()
    secret = "whsec_test"
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    monkeypatch.setattr(
        "ucp_server.webhooks.queue_github_issue_index",
        lambda *a, **k: "inbound-gh",
    )
    result = handle_inbound_webhook(
        source="github",
        body=body,
        signature=sig,
        signing_secret=secret,
        redis_url="redis://localhost/0",
    )
    assert result["task_id"] == "inbound-gh"


def test_handle_github_webhook_bad_signature():
    with pytest.raises(PermissionError):
        handle_github_webhook(
            body=b"{}",
            signature="sha256=dead",
            secret="secret",
            redis_url="redis://localhost/0",
        )
