"""Map a GitHub issue bundle to a valid Universal Context Package.

Pure functions only: no network, no clock reads (``now`` is injectable),
so the whole mapping is testable on fixtures. No LLM in the loop — the
structure itself carries the meaning; summarization can be layered on top.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

SPEC_VERSION = "0.1.0"
GENERATOR = {"name": "ucp-gen", "version": "0.3.1", "url": "https://github.com/ucpcore/ucp"}

# Comments matching these are surfaced as proposed decisions (cheap heuristic;
# merged PRs are the reliable "accepted" signal).
_DECISION_RE = re.compile(
    r"\b(we (?:decided|agreed|will go with)|decision:|let's go with|going with)\b", re.IGNORECASE
)

_MAX_HISTORY = 20
_MAX_COMMENT_CLAIMS = 10
_EXCERPT_LEN = 280
_DEFAULT_FETCH_LIMIT = 200


def _hash(text: str) -> str:
    return "sha256:" + hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _actor(user: Optional[dict]) -> Optional[dict]:
    if not user:
        return None
    return {"id": f"github:{user['login']}", "display_name": user["login"]}


def _excerpt(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    flat = " ".join(text.split())
    if len(flat) <= _EXCERPT_LEN:
        return flat
    cut = flat.rfind(" ", 0, _EXCERPT_LEN)
    return flat[: cut if cut > _EXCERPT_LEN // 2 else _EXCERPT_LEN] + "…"


def _first_paragraph(text: Optional[str], fallback: str) -> str:
    """First block of the body that carries meaning, not template markup.

    Issue templates produce bodies like "## Description\n\n<the actual text>";
    headers, images, HTML comments, tables and code fences are skipped.
    """
    if not text:
        return fallback
    # Drop fenced code blocks entirely: logs/tracebacks are not a summary.
    prose = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    prose = re.sub(r"\{code.*?\{code\}", "", prose, flags=re.DOTALL)  # Jira wiki code blocks
    for block in re.split(r"\n\s*\n", prose.strip()):
        lines = [ln for ln in block.splitlines()
                 if not ln.lstrip().startswith(("#", "<!--", "![", "|"))
                 and not re.match(r"\s*h[1-6]\.\s", ln)]  # Jira wiki headers
        cleaned = " ".join(" ".join(lines).split())
        if cleaned:
            return cleaned[:600]
    return fallback


def _iso(value: Optional[str]) -> Optional[str]:
    return value or None


def _dedupe_decisions(decisions: list[dict]) -> list[dict]:
    """Drop proposed comment decisions when a merged PR decision exists."""
    if not any(d.get("status") == "accepted" for d in decisions):
        return decisions
    return [d for d in decisions if d.get("status") != "proposed"]


def _build_coverage(
    bundle: dict[str, Any],
    *,
    comments_retrieved: int,
    comments_represented: int,
    timeline_retrieved: int,
    timeline_represented: int,
    sources_included: int,
) -> dict[str, Any]:
    """Honesty block for partial fetch / representation (RFC-0006 §3.1)."""
    issue = bundle["issue"]
    pulls = bundle.get("linked_pulls", [])
    fetch_meta = bundle.get("fetch_meta") or {}
    comments_limit = int(fetch_meta.get("comments_limit", _DEFAULT_FETCH_LIMIT))
    timeline_limit = int(fetch_meta.get("timeline_limit", _DEFAULT_FETCH_LIMIT))

    comments_available = issue.get("comments")
    if comments_available is not None:
        comments_available = int(comments_available)

    comment_truncated = (
        (comments_available is not None and comments_available > comments_retrieved)
        or comments_retrieved >= comments_limit
        or comments_represented < comments_retrieved
    )
    timeline_truncated = (
        timeline_retrieved >= timeline_limit
        or timeline_represented < timeline_retrieved
    )
    truncated = comment_truncated or timeline_truncated

    streams: list[dict[str, Any]] = [
        {
            "kind": "comments",
            "available": comments_available,
            "retrieved": comments_retrieved,
            "represented": comments_represented,
            "fetch_limit": comments_limit,
        },
        {
            "kind": "timeline",
            "available": None,
            "retrieved": timeline_retrieved,
            "represented": timeline_represented,
            "fetch_limit": timeline_limit,
        },
    ]

    considered = comments_retrieved + timeline_retrieved + 1 + len(pulls)
    if comments_available is not None:
        considered = comments_available + timeline_retrieved + 1 + len(pulls)

    return {
        "truncated": truncated,
        "sources_considered": considered,
        "sources_included": sources_included,
        "streams": streams,
    }


def build_package(
    bundle: dict[str, Any],
    since: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build a UCP dict (spec 0.1.0, profile ucp-core) from a GitHub bundle."""
    owner, repo = bundle["owner"], bundle["repo"]
    issue = bundle["issue"]
    comments = bundle.get("comments", [])
    timeline = bundle.get("timeline", [])
    pulls = bundle.get("linked_pulls", [])
    number = issue["number"]
    full = f"{owner}/{repo}"
    generated_at = (now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")

    sources: dict[str, dict] = {}
    sources["issue"] = {
        "system": "github",
        "type": "ticket",
        "title": f"{full}#{number}: {issue['title']}",
        "url": issue["html_url"],
        "author": _actor(issue.get("user")),
        "created_at": _iso(issue.get("created_at")),
        "updated_at": _iso(issue.get("updated_at")),
        "content_hash": _hash(issue.get("body") or ""),
        "retrieved_at": generated_at,
        "excerpt": _excerpt(issue.get("body")),
    }
    for comment in comments:
        sources[f"comment-{comment['id']}"] = {
            "system": "github",
            "type": "comment",
            "title": f"Comment by {comment['user']['login']}",
            "url": comment["html_url"],
            "author": _actor(comment.get("user")),
            "created_at": _iso(comment.get("created_at")),
            "content_hash": _hash(comment.get("body") or ""),
            "retrieved_at": generated_at,
            "excerpt": _excerpt(comment.get("body")),
        }
    for pull in pulls:
        sources[f"pr-{pull['number']}"] = {
            "system": "github",
            "type": "pull_request",
            "title": f"PR #{pull['number']}: {pull['title']}",
            "url": pull["html_url"],
            "author": _actor(pull.get("user")),
            "created_at": _iso(pull.get("created_at")),
            "updated_at": _iso(pull.get("updated_at")),
            "content_hash": _hash(pull.get("body") or ""),
            "retrieved_at": generated_at,
            "excerpt": _excerpt(pull.get("body")),
        }

    # --- must_know: state of the world, highest salience first ---------------
    must_know: list[dict] = []

    def claim(cid: str, text: str, salience: float, srcs: list[str], **extra: Any) -> None:
        must_know.append({"id": cid, "text": text, "salience": salience, "sources": srcs, **extra})

    state = issue.get("state", "open")
    state_text = f"Issue is {state}"
    if state == "closed" and issue.get("state_reason"):
        state_text += f" ({issue['state_reason']})"
    claim("state", state_text, 0.95, ["issue"], kind="status",
          asserted_at=_iso(issue.get("updated_at")))

    assignees = [a["login"] for a in issue.get("assignees") or []]
    if assignees:
        claim("assignees", "Assigned to " + ", ".join(assignees), 0.85, ["issue"], kind="fact")
    else:
        claim("assignees", "Nobody is assigned", 0.6, ["issue"], kind="fact")

    if issue.get("milestone"):
        milestone = issue["milestone"]
        text = f"Milestone: {milestone['title']}"
        if milestone.get("due_on"):
            text += f" (due {milestone['due_on'][:10]})"
        claim("milestone", text, 0.8, ["issue"], kind="constraint")

    labels = [label["name"] for label in issue.get("labels") or []]
    if labels:
        claim("labels", "Labels: " + ", ".join(labels), 0.65, ["issue"], kind="fact")

    for pull in pulls:
        merged = bool(pull.get("merged_at"))
        pr_state = "merged" if merged else pull.get("state", "open")
        claim(
            f"pr-{pull['number']}-state",
            f"PR #{pull['number']} \u201c{pull['title']}\u201d is {pr_state}",
            0.9 if merged else 0.8,
            [f"pr-{pull['number']}"],
            kind="status",
            asserted_at=_iso(pull.get("merged_at") or pull.get("updated_at")),
        )

    # Recent comments become low-salience claims: newer ⇒ more relevant.
    # Empty bodies are filtered before the recency window so they cannot
    # crowd out substantive comments.
    recent = sorted(
        (c for c in comments if (c.get("body") or "").strip()),
        key=lambda c: c.get("created_at") or "",
        reverse=True,
    )
    for rank, comment in enumerate(recent[:_MAX_COMMENT_CLAIMS]):
        body = _excerpt(comment.get("body"))
        claim(
            f"comment-{comment['id']}-gist",
            f"{comment['user']['login']}: {body}",
            max(0.2, 0.55 - 0.05 * rank),
            [f"comment-{comment['id']}"],
            kind="fact",
            asserted_at=_iso(comment.get("created_at")),
        )

    # --- decisions ------------------------------------------------------------
    decisions: list[dict] = []
    for pull in pulls:
        if pull.get("merged_at"):
            decisions.append({
                "id": f"decision-pr-{pull['number']}",
                "decision": f"Implemented via PR #{pull['number']}: {pull['title']}",
                "status": "accepted",
                "sources": [f"pr-{pull['number']}"],
                "decided_by": _actor(pull.get("merged_by") or pull.get("user")),
                "decided_at": _iso(pull.get("merged_at")),
            })
    for comment in comments:
        body = comment.get("body") or ""
        if _DECISION_RE.search(body):
            decisions.append({
                "id": f"decision-comment-{comment['id']}",
                "decision": _excerpt(body) or "",
                "status": "proposed",
                "sources": [f"comment-{comment['id']}"],
                "decided_by": _actor(comment.get("user")),
                "decided_at": _iso(comment.get("created_at")),
            })
    decisions = _dedupe_decisions(decisions)

    # --- history + context_diff from the timeline ------------------------------
    history: list[dict] = [{
        "occurred_at": issue["created_at"],
        "summary": f"Issue opened by {issue['user']['login']}",
        "actor": _actor(issue.get("user")),
        "sources": ["issue"],
    }]
    diff_changes: list[dict] = []

    def timeline_summary(event: dict) -> Optional[tuple[str, str]]:
        kind = event.get("event")
        actor_login = (event.get("actor") or {}).get("login", "someone")
        if kind == "labeled":
            return f"{actor_login} added label \u201c{event['label']['name']}\u201d", "updated"
        if kind == "unlabeled":
            return f"{actor_login} removed label \u201c{event['label']['name']}\u201d", "updated"
        if kind == "assigned":
            return f"{actor_login} assigned {(event.get('assignee') or {}).get('login', '?')}", "updated"
        if kind == "closed":
            return f"{actor_login} closed the issue", "status_changed"
        if kind == "reopened":
            return f"{actor_login} reopened the issue", "status_changed"
        if kind == "milestoned":
            return f"{actor_login} set milestone \u201c{(event.get('milestone') or {}).get('title', '?')}\u201d", "updated"
        if kind == "cross-referenced":
            source_issue = (event.get("source") or {}).get("issue") or {}
            ref_kind = "PR" if source_issue.get("pull_request") else "issue"
            return f"Referenced by {ref_kind} #{source_issue.get('number', '?')}", "added"
        if kind == "commented":
            return f"{actor_login} commented", "added"
        return None

    for event in timeline:
        occurred = event.get("created_at") or event.get("submitted_at")
        described = timeline_summary(event)
        if not occurred or not described:
            continue
        summary_text, change_type = described
        history.append({
            "occurred_at": occurred,
            "summary": summary_text,
            "actor": _actor(event.get("actor")),
            "sources": ["issue"],
        })
        if since and occurred > since:
            diff_changes.append({
                "type": change_type,
                "summary": summary_text,
                "occurred_at": occurred,
                "actor": _actor(event.get("actor")),
                "sources": ["issue"],
            })

    history.sort(key=lambda e: e["occurred_at"])
    history = history[-_MAX_HISTORY:]
    timeline_represented = sum(
        1 for event in history if not event["summary"].startswith("Issue opened by")
    )

    # --- related objects --------------------------------------------------------
    related = [{
        "ref": {"system": "github", "type": "pull_request",
                "id": f"{full}#{pull['number']}", "url": pull["html_url"]},
        "title": pull["title"],
        "relation": "implements" if pull.get("merged_at") else "references",
        "salience": 0.9 if pull.get("merged_at") else 0.7,
    } for pull in pulls]

    # Keep only sources that something actually cites: on busy issues the
    # registry would otherwise dwarf the content (200 comments -> 200 sources)
    # and blow the token budget of the rendered Sources section.
    referenced: set[str] = {"issue"}
    for section in (must_know, decisions):
        for item in section:
            referenced.update(item["sources"])
    sources = {key: value for key, value in sources.items() if key in referenced}

    comments_represented = sum(
        1 for c in must_know if c["id"].startswith("comment-") and c["id"].endswith("-gist")
    )
    coverage = _build_coverage(
        bundle,
        comments_retrieved=len(comments),
        comments_represented=comments_represented,
        timeline_retrieved=len(timeline),
        timeline_represented=timeline_represented,
        sources_included=len(sources),
    )

    profiles = ["ucp-core"]
    package: dict[str, Any] = {
        "ucp_version": SPEC_VERSION,
        "id": f"urn:uuid:{uuid.uuid4()}",
        "generated_at": generated_at,
        "generator": GENERATOR,
        "profiles": profiles,
        "entity": {
            "ref": {"system": "github", "type": "issue",
                    "id": f"{full}#{number}", "url": issue["html_url"]},
            "title": issue["title"],
            "status": state,
            **({"assignee": _actor(issue["assignee"])} if issue.get("assignee") else {}),
        },
        "summary": {
            "text": _first_paragraph(issue.get("body"), issue["title"]),
            "sources": ["issue"],
        },
        "must_know": must_know,
        "decisions": decisions,
        "history": history,
        "related_objects": related,
        "sources": sources,
        "coverage": coverage,
    }
    if since:
        profiles.append("ucp-temporal")
        package["context_diff"] = {"since": since, "changes": diff_changes}
    return package


def llm_docs(bundle: dict[str, Any], generated_at: str) -> list[dict[str, Any]]:
    """Full-text documents for optional LLM enhancement (see ``llm.py``)."""
    issue = bundle["issue"]
    full = f"{bundle['owner']}/{bundle['repo']}"
    docs = [{
        "key": "issue",
        "label": f"Issue {full}#{issue['number']} by {issue['user']['login']}",
        "text": f"{issue['title']}\n\n{issue.get('body') or ''}",
        "source": {
            "system": "github", "type": "ticket",
            "title": f"{full}#{issue['number']}: {issue['title']}",
            "url": issue["html_url"],
            "author": _actor(issue.get("user")),
            "created_at": _iso(issue.get("created_at")),
            "content_hash": _hash(issue.get("body") or ""),
            "retrieved_at": generated_at,
        },
    }]
    for comment in bundle.get("comments", []):
        if not (comment.get("body") or "").strip():
            continue
        docs.append({
            "key": f"comment-{comment['id']}",
            "label": f"Comment by {comment['user']['login']} at {comment.get('created_at', '?')}",
            "text": comment["body"],
            "source": {
                "system": "github", "type": "comment",
                "title": f"Comment by {comment['user']['login']}",
                "url": comment["html_url"],
                "author": _actor(comment.get("user")),
                "created_at": _iso(comment.get("created_at")),
                "content_hash": _hash(comment.get("body") or ""),
                "retrieved_at": generated_at,
            },
        })
    for pull in bundle.get("linked_pulls", []):
        docs.append({
            "key": f"pr-{pull['number']}",
            "label": f"PR #{pull['number']} ({'merged' if pull.get('merged_at') else pull.get('state', 'open')})",
            "text": f"{pull['title']}\n\n{pull.get('body') or ''}",
            "source": {
                "system": "github", "type": "pull_request",
                "title": f"PR #{pull['number']}: {pull['title']}",
                "url": pull["html_url"],
                "author": _actor(pull.get("user")),
                "created_at": _iso(pull.get("created_at")),
                "content_hash": _hash(pull.get("body") or ""),
                "retrieved_at": generated_at,
            },
        })
    return docs
