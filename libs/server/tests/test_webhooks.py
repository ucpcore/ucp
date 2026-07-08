"""GitHub webhook parsing and signature verification."""
import hashlib
import hmac
import json

import pytest

from ucp_server.webhooks import handle_github_webhook, parse_github_webhook, verify_github_signature


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


def test_parse_github_comment_ignored_action():
    payload = {"action": "labeled", "issue": {"number": 1}}
    assert parse_github_webhook(payload) is None


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

    monkeypatch.setattr(
        "contextos_engine.admin.webhooks.trigger_github_issue_index",
        fake_trigger,
    )

    result = handle_github_webhook(
        body=body,
        signature=sig,
        secret=secret,
        redis_url="redis://localhost/0",
    )
    assert result["status"] == "queued"
    assert result["task_id"] == "task-abc"
    assert calls == [("acme", "demo", 7, "redis://localhost/0")]


def test_handle_github_webhook_bad_signature():
    with pytest.raises(PermissionError):
        handle_github_webhook(
            body=b"{}",
            signature="sha256=dead",
            secret="secret",
            redis_url="redis://localhost/0",
        )
