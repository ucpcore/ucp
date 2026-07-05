"""Map a Jira issue bundle to a valid Universal Context Package.

Pure functions, testable on fixtures — same contract as the GitHub mapping
in ``build.py``. Jira gives us richer formal semantics for free: an explicit
status workflow, a resolution, typed issue links (blocks / is blocked by)
and a changelog instead of a timeline.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .build import (
    GENERATOR,
    SPEC_VERSION,
    _DECISION_RE,
    _MAX_COMMENT_CLAIMS,
    _MAX_HISTORY,
    _excerpt,
    _first_paragraph,
    _hash,
    _iso,
)

# Changelog fields that carry workflow meaning; the rest (rank, sprint ids…)
# is noise for a task context.
_HISTORY_FIELDS = {"status", "assignee", "priority", "resolution", "Fix Version", "labels", "duedate"}


def _actor(user: Optional[dict]) -> Optional[dict]:
    if not user:
        return None
    uid = user.get("accountId") or user.get("name") or user.get("key") or "unknown"
    return {"id": f"jira:{uid}", "display_name": user.get("displayName") or uid}


def _display(user: Optional[dict]) -> str:
    return (user or {}).get("displayName") or "someone"


def build_jira_package(
    bundle: dict[str, Any],
    since: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build a UCP dict (spec 0.1.0, profile ucp-core) from a Jira bundle."""
    base_url = bundle["base_url"].rstrip("/")
    issue = bundle["issue"]
    comments = bundle.get("comments", [])
    fields = issue["fields"]
    key = issue["key"]
    browse_url = f"{base_url}/browse/{key}"
    generated_at = (now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")

    status = ((fields.get("status") or {}).get("name")) or "Unknown"
    resolution = (fields.get("resolution") or {}).get("name")

    sources: dict[str, dict] = {
        "issue": {
            "system": "jira",
            "type": "ticket",
            "title": f"{key}: {fields.get('summary', '')}",
            "url": browse_url,
            "author": _actor(fields.get("reporter")),
            "created_at": _iso(fields.get("created")),
            "updated_at": _iso(fields.get("updated")),
            "content_hash": _hash(fields.get("description") or ""),
            "retrieved_at": generated_at,
            "excerpt": _excerpt(fields.get("description")),
        }
    }
    for comment in comments:
        sources[f"comment-{comment['id']}"] = {
            "system": "jira",
            "type": "comment",
            "title": f"Comment by {_display(comment.get('author'))}",
            "url": f"{browse_url}?focusedCommentId={comment['id']}",
            "author": _actor(comment.get("author")),
            "created_at": _iso(comment.get("created")),
            "content_hash": _hash(comment.get("body") or ""),
            "retrieved_at": generated_at,
            "excerpt": _excerpt(comment.get("body")),
        }

    # --- must_know --------------------------------------------------------------
    must_know: list[dict] = []

    def claim(cid: str, text: str, salience: float, srcs: list[str], **extra: Any) -> None:
        must_know.append({"id": cid, "text": text, "salience": salience, "sources": srcs, **extra})

    status_text = f"Status: {status}"
    if resolution:
        status_text += f" (resolution: {resolution})"
    claim("status", status_text, 0.95, ["issue"], kind="status",
          asserted_at=_iso(fields.get("updated")))

    if fields.get("assignee"):
        claim("assignee", f"Assigned to {_display(fields['assignee'])}", 0.85, ["issue"], kind="fact")
    else:
        claim("assignee", "Nobody is assigned", 0.6, ["issue"], kind="fact")

    if fields.get("priority"):
        claim("priority", f"Priority: {fields['priority']['name']}", 0.7, ["issue"], kind="fact")

    if fields.get("duedate"):
        claim("duedate", f"Due {fields['duedate']}", 0.85, ["issue"], kind="constraint")

    versions = [v["name"] for v in fields.get("fixVersions") or []]
    if versions:
        claim("fix-versions", "Fix version: " + ", ".join(versions), 0.8, ["issue"], kind="constraint")

    labels = fields.get("labels") or []
    if labels:
        claim("labels", "Labels: " + ", ".join(labels), 0.65, ["issue"], kind="fact")

    # Typed issue links: "is blocked by" is a constraint, everything else a fact.
    dependencies: list[dict] = []
    related: list[dict] = []
    for link in fields.get("issuelinks") or []:
        if link.get("inwardIssue"):
            other, relation = link["inwardIssue"], (link.get("type") or {}).get("inward", "relates to")
        elif link.get("outwardIssue"):
            other, relation = link["outwardIssue"], (link.get("type") or {}).get("outward", "relates to")
        else:
            continue
        other_key = other["key"]
        other_title = (other.get("fields") or {}).get("summary", other_key)
        other_ref = {"system": "jira", "type": "issue", "id": other_key,
                     "url": f"{base_url}/browse/{other_key}"}
        blocked = "blocked" in relation.lower()
        claim(
            f"link-{other_key}",
            f"{relation} {other_key} \u201c{other_title}\u201d",
            0.85 if blocked else 0.7,
            ["issue"],
            kind="constraint" if blocked else "fact",
        )
        if blocked:
            dependencies.append(other_ref)
        related.append({"ref": other_ref, "title": other_title, "relation": relation,
                        "salience": 0.85 if blocked else 0.6})

    if fields.get("parent"):
        parent = fields["parent"]
        related.append({
            "ref": {"system": "jira", "type": "issue", "id": parent["key"],
                    "url": f"{base_url}/browse/{parent['key']}"},
            "title": (parent.get("fields") or {}).get("summary", parent["key"]),
            "relation": "child of",
            "salience": 0.7,
        })
    for subtask in fields.get("subtasks") or []:
        related.append({
            "ref": {"system": "jira", "type": "issue", "id": subtask["key"],
                    "url": f"{base_url}/browse/{subtask['key']}"},
            "title": (subtask.get("fields") or {}).get("summary", subtask["key"]),
            "relation": "subtask",
            "salience": 0.5,
        })

    # Recent substantive comments, newer first.
    recent = sorted(
        (c for c in comments if (c.get("body") or "").strip()),
        key=lambda c: c.get("created") or "",
        reverse=True,
    )
    for rank, comment in enumerate(recent[:_MAX_COMMENT_CLAIMS]):
        claim(
            f"comment-{comment['id']}-gist",
            f"{_display(comment.get('author'))}: {_excerpt(comment.get('body'))}",
            max(0.2, 0.55 - 0.05 * rank),
            [f"comment-{comment['id']}"],
            kind="fact",
            asserted_at=_iso(comment.get("created")),
        )

    # --- decisions ----------------------------------------------------------------
    decisions: list[dict] = []
    if resolution:
        decisions.append({
            "id": "decision-resolution",
            "decision": f"Resolved as {resolution}",
            "status": "accepted",
            "sources": ["issue"],
            "decided_at": _iso(fields.get("resolutiondate")),
        })
    for comment in comments:
        body = comment.get("body") or ""
        if _DECISION_RE.search(body):
            decisions.append({
                "id": f"decision-comment-{comment['id']}",
                "decision": _excerpt(body) or "",
                "status": "proposed",
                "sources": [f"comment-{comment['id']}"],
                "decided_by": _actor(comment.get("author")),
                "decided_at": _iso(comment.get("created")),
            })

    # --- history + context_diff from the changelog ----------------------------------
    history: list[dict] = [{
        "occurred_at": fields["created"],
        "summary": f"Issue created by {_display(fields.get('reporter'))}",
        "actor": _actor(fields.get("reporter")),
        "sources": ["issue"],
    }]
    diff_changes: list[dict] = []

    def record(occurred: str, summary: str, change_type: str, actor: Optional[dict]) -> None:
        history.append({"occurred_at": occurred, "summary": summary,
                        "actor": _actor(actor), "sources": ["issue"]})
        if since and occurred > since:
            diff_changes.append({"type": change_type, "summary": summary,
                                 "occurred_at": occurred, "actor": _actor(actor),
                                 "sources": ["issue"]})

    for entry in (issue.get("changelog") or {}).get("histories", []):
        occurred = entry.get("created")
        if not occurred:
            continue
        who = _display(entry.get("author"))
        for item in entry.get("items", []):
            field_name = item.get("field", "")
            if field_name not in _HISTORY_FIELDS:
                continue
            was, now_val = item.get("fromString") or "—", item.get("toString") or "—"
            change_type = "status_changed" if field_name == "status" else "updated"
            record(occurred, f"{who} changed {field_name}: {was} \u2192 {now_val}",
                   change_type, entry.get("author"))

    for comment in comments:
        if comment.get("created"):
            record(comment["created"], f"{_display(comment.get('author'))} commented",
                   "added", comment.get("author"))

    history.sort(key=lambda e: e["occurred_at"])
    history = history[-_MAX_HISTORY:]

    # Keep only cited sources (same rationale as the GitHub mapping).
    referenced: set[str] = {"issue"}
    for section in (must_know, decisions):
        for item in section:
            referenced.update(item["sources"])
    sources = {k: v for k, v in sources.items() if k in referenced}

    profiles = ["ucp-core"]
    package: dict[str, Any] = {
        "ucp_version": SPEC_VERSION,
        "id": f"urn:uuid:{uuid.uuid4()}",
        "generated_at": generated_at,
        "generator": GENERATOR,
        "profiles": profiles,
        "entity": {
            "ref": {"system": "jira",
                    "type": ((fields.get("issuetype") or {}).get("name") or "issue").lower(),
                    "id": key, "url": browse_url},
            "title": fields.get("summary", key),
            "status": status,
            **({"assignee": _actor(fields["assignee"])} if fields.get("assignee") else {}),
        },
        "summary": {
            "text": _first_paragraph(fields.get("description"), fields.get("summary", key)),
            "sources": ["issue"],
        },
        "must_know": must_know,
        "decisions": decisions,
        "history": history,
        "dependencies": dependencies,
        "related_objects": related,
        "sources": sources,
    }
    if since:
        profiles.append("ucp-temporal")
        package["context_diff"] = {"since": since, "changes": diff_changes}
    return package


def llm_docs(bundle: dict[str, Any], generated_at: str) -> list[dict[str, Any]]:
    """Full-text documents for optional LLM enhancement (see ``llm.py``)."""
    base_url = bundle["base_url"].rstrip("/")
    issue = bundle["issue"]
    fields = issue["fields"]
    key = issue["key"]
    browse_url = f"{base_url}/browse/{key}"
    docs = [{
        "key": "issue",
        "label": f"Issue {key} by {_display(fields.get('reporter'))}",
        "text": f"{fields.get('summary', '')}\n\n{fields.get('description') or ''}",
        "source": {
            "system": "jira", "type": "ticket",
            "title": f"{key}: {fields.get('summary', '')}",
            "url": browse_url,
            "author": _actor(fields.get("reporter")),
            "created_at": _iso(fields.get("created")),
            "content_hash": _hash(fields.get("description") or ""),
            "retrieved_at": generated_at,
        },
    }]
    for comment in bundle.get("comments", []):
        if not (comment.get("body") or "").strip():
            continue
        docs.append({
            "key": f"comment-{comment['id']}",
            "label": f"Comment by {_display(comment.get('author'))} at {comment.get('created', '?')}",
            "text": comment["body"],
            "source": {
                "system": "jira", "type": "comment",
                "title": f"Comment by {_display(comment.get('author'))}",
                "url": f"{browse_url}?focusedCommentId={comment['id']}",
                "author": _actor(comment.get("author")),
                "created_at": _iso(comment.get("created")),
                "content_hash": _hash(comment.get("body") or ""),
                "retrieved_at": generated_at,
            },
        })
    return docs
