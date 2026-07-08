"""GitHub webhook ingestion → Celery sync-hot (RFC-0002 §3)."""
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


def queue_github_issue_index(
    owner: str, repo: str, number: int, *, redis_url: str
) -> str:
    """Enqueue single-issue re-index (Context OS engine when installed)."""
    from contextos_engine.admin.webhooks import trigger_github_issue_index

    return trigger_github_issue_index(owner, repo, number, redis_url=redis_url)


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
    parsed = parse_github_webhook(payload)
    if parsed is None:
        logger.debug("github webhook ignored: action=%s", payload.get("action"))
        return {"status": "ignored", "reason": "no indexable issue event"}

    owner, repo, number = parsed
    task_id = queue_github_issue_index(owner, repo, number, redis_url=redis_url)
    logger.info("github webhook queued index %s/%s#%d task=%s", owner, repo, number, task_id)
    return {
        "status": "queued",
        "repo": f"{owner}/{repo}",
        "issue": number,
        "task_id": task_id,
    }
