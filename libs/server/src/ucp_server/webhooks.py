"""Inbound webhooks: GitHub, Jira, Confluence → Celery sync-hot (RFC-0002 §3)."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_ISSUE_ACTIONS = frozenset(
    {"opened", "edited", "closed", "reopened", "deleted", "transferred"}
)
_COMMENT_ACTIONS = frozenset({"created", "edited", "deleted"})
_JIRA_ISSUE_EVENTS = frozenset(
    {
        "jira:issue_created",
        "jira:issue_updated",
        "jira:issue_deleted",
        "comment_created",
        "comment_updated",
    }
)
_CONFLUENCE_PAGE_EVENTS = frozenset(
    {
        "page_created",
        "page_updated",
        "page_restored",
        "page_trashed",
        "page_moved",
    }
)


def verify_github_signature(payload: bytes, signature: str, secret: str) -> bool:
    if not signature.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    return hmac.compare_digest(expected, signature)


def parse_github_webhook(payload: dict[str, Any]) -> Optional[tuple[str, str, int]]:
    """Return (owner, repo, issue_number) when the event should trigger re-index."""
    event = payload.get("action")
    if event in _ISSUE_ACTIONS and "issue" in payload:
        issue = payload["issue"]
        repo = payload.get("repository") or {}
        full = repo.get("full_name") or ""
        if "/" not in full:
            return None
        owner, name = full.split("/", 1)
        num = issue.get("number")
        if isinstance(num, int) and num > 0:
            return owner, name, num
    if event in _COMMENT_ACTIONS and "issue" in payload:
        issue = payload["issue"]
        repo = payload.get("repository") or {}
        full = repo.get("full_name") or ""
        if "/" not in full:
            return None
        owner, name = full.split("/", 1)
        num = issue.get("number")
        if isinstance(num, int) and num > 0:
            return owner, name, num
    return None


def parse_jira_webhook(payload: dict[str, Any]) -> Optional[str]:
    """Return issue key (e.g. KAN-7) when event should trigger re-index."""
    event = payload.get("webhookEvent") or ""
    if event not in _JIRA_ISSUE_EVENTS and not event.startswith("jira:issue"):
        if event not in ("comment_created", "comment_updated"):
            return None
    issue = payload.get("issue") or {}
    key = issue.get("key")
    if isinstance(key, str) and key.strip():
        return key.strip().upper()
    return None


def parse_confluence_webhook(payload: dict[str, Any]) -> Optional[str]:
    """Return external_id SPACE:PAGE_ID for index_page."""
    event = (payload.get("event") or payload.get("webhookEvent") or "").lower()
    if event and event not in _CONFLUENCE_PAGE_EVENTS and "page" not in event:
        return None
    page = payload.get("page") or payload.get("content") or {}
    page_id = page.get("id")
    space_key = page.get("spaceKey")
    if not space_key:
        space = page.get("space") or {}
        space_key = space.get("key") or space.get("spaceKey")
    if space_key and page_id is not None:
        return f"{space_key}:{page_id}"
    return None


def queue_github_issue_index(
    owner: str, repo: str, number: int, *, redis_url: str
) -> str:
    from contextos_engine.admin.webhooks import trigger_github_issue_index

    return trigger_github_issue_index(owner, repo, number, redis_url=redis_url)


def queue_jira_issue_index(key: str, *, redis_url: str) -> str:
    from contextos_engine.admin.webhooks import trigger_jira_issue_index

    return trigger_jira_issue_index(key, redis_url=redis_url)


def queue_confluence_page_index(external_id: str, *, redis_url: str) -> str:
    from contextos_engine.admin.webhooks import trigger_confluence_page_index

    return trigger_confluence_page_index(external_id, redis_url=redis_url)


def _dispatch_github(payload: dict[str, Any], *, redis_url: str) -> dict[str, Any]:
    parsed = parse_github_webhook(payload)
    if parsed is None:
        return {"status": "ignored", "reason": "no indexable issue event"}
    owner, repo, number = parsed
    task_id = queue_github_issue_index(owner, repo, number, redis_url=redis_url)
    logger.info("github webhook queued %s/%s#%d task=%s", owner, repo, number, task_id)
    return {
        "status": "queued",
        "source": "github",
        "repo": f"{owner}/{repo}",
        "issue": number,
        "task_id": task_id,
    }


def _dispatch_jira(payload: dict[str, Any], *, redis_url: str) -> dict[str, Any]:
    key = parse_jira_webhook(payload)
    if key is None:
        return {"status": "ignored", "reason": "no indexable jira issue event"}
    task_id = queue_jira_issue_index(key, redis_url=redis_url)
    logger.info("jira webhook queued %s task=%s", key, task_id)
    return {"status": "queued", "source": "jira", "issue_key": key, "task_id": task_id}


def _dispatch_confluence(payload: dict[str, Any], *, redis_url: str) -> dict[str, Any]:
    external_id = parse_confluence_webhook(payload)
    if external_id is None:
        return {"status": "ignored", "reason": "no indexable confluence page event"}
    task_id = queue_confluence_page_index(external_id, redis_url=redis_url)
    logger.info("confluence webhook queued %s task=%s", external_id, task_id)
    return {
        "status": "queued",
        "source": "confluence",
        "page": external_id,
        "task_id": task_id,
    }


def handle_github_webhook(
    *,
    body: bytes,
    signature: str,
    secret: str,
    redis_url: str,
) -> dict[str, Any]:
    if not secret:
        raise ValueError("GITHUB_WEBHOOK_SECRET is not configured")
    if not verify_github_signature(body, signature, secret):
        raise PermissionError("invalid GitHub webhook signature")
    payload = json.loads(body.decode("utf-8"))
    return _dispatch_github(payload, redis_url=redis_url)


def handle_jira_webhook(
    *,
    body: bytes,
    secret: Optional[str],
    configured_secret: Optional[str],
    redis_url: str,
) -> dict[str, Any]:
    if configured_secret:
        header = (secret or "").strip()
        if not header or not hmac.compare_digest(header, configured_secret):
            raise PermissionError("invalid Jira webhook secret")
    payload = json.loads(body.decode("utf-8"))
    return _dispatch_jira(payload, redis_url=redis_url)


def handle_confluence_webhook(
    *,
    body: bytes,
    secret: Optional[str],
    configured_secret: Optional[str],
    redis_url: str,
) -> dict[str, Any]:
    if configured_secret:
        header = (secret or "").strip()
        if not header or not hmac.compare_digest(header, configured_secret):
            raise PermissionError("invalid Confluence webhook secret")
    payload = json.loads(body.decode("utf-8"))
    return _dispatch_confluence(payload, redis_url=redis_url)


def handle_inbound_webhook(
    *,
    source: str,
    body: bytes,
    signature: str,
    signing_secret: str,
    redis_url: str,
) -> dict[str, Any]:
    """User-configured endpoint: URL token already verified; optional GitHub HMAC."""
    if source == "github" and signature:
        if not verify_github_signature(body, signature, signing_secret):
            raise PermissionError("invalid GitHub webhook signature")
    payload = json.loads(body.decode("utf-8"))
    if source == "github":
        return _dispatch_github(payload, redis_url=redis_url)
    if source == "jira":
        return _dispatch_jira(payload, redis_url=redis_url)
    if source == "confluence":
        return _dispatch_confluence(payload, redis_url=redis_url)
    raise ValueError(f"unknown webhook source: {source}")
