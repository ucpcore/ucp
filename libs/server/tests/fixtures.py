"""A realistic GitHub issue bundle (trimmed to the fields ucp-gen reads)."""


def user(login: str) -> dict:
    return {"login": login}


GITHUB_BUNDLE = {
    "owner": "acme",
    "repo": "rocket",
    "issue": {
        "number": 42,
        "title": "Payment webhook drops events under load",
        "state": "closed",
        "state_reason": "completed",
        "html_url": "https://github.com/acme/rocket/issues/42",
        "user": user("alice"),
        "created_at": "2026-06-01T09:00:00Z",
        "updated_at": "2026-06-20T18:00:00Z",
        "body": "When more than ~50 webhook events arrive per second, some are dropped.",
        "assignee": user("bob"),
        "assignees": [user("bob")],
        "labels": [{"name": "bug"}],
    },
    "comments": [
        {
            "id": 100,
            "user": user("bob"),
            "created_at": "2026-06-02T10:00:00Z",
            "html_url": "https://github.com/acme/rocket/issues/42#issuecomment-100",
            "body": "Reproduced. The consumer ack's before processing finishes.",
        },
    ],
    "timeline": [
        {"event": "closed", "created_at": "2026-06-20T18:00:00Z", "actor": user("bob")},
    ],
    "linked_pulls": [],
}

JIRA_BUNDLE = {
    "base_url": "https://acme.atlassian.net",
    "issue": {
        "key": "PAY-7",
        "fields": {
            "summary": "Rotate webhook signing keys",
            "description": "v1 keys are revoked on Aug 1; services must migrate.",
            "status": {"name": "In Progress"},
            "reporter": {"accountId": "u1", "displayName": "Alice"},
            "created": "2026-06-01T09:00:00.000+0000",
            "updated": "2026-06-20T18:00:00.000+0000",
        },
        "changelog": {"histories": []},
    },
    "comments": [],
}

DOCUMENT_BUNDLE = {
    "source_system": "confluence",
    "object_type": "page",
    "external_id": "DOCS:123456",
    "title": "Architecture RFC v2",
    "url": "https://example.atlassian.net/wiki/spaces/DOCS/pages/123456",
    "parent": {"type": "space", "id": "DOCS", "name": "Confluence space DOCS"},
    "author": {"email": "author@example.com", "id": "abc123"},
    "created_at": "2026-01-15T10:00:00.000Z",
    "updated_at": "2026-06-01T14:30:00.000Z",
    "content_text": "This RFC describes the Context OS ingestion pipeline.",
    "content_hash": "sha256:" + "a" * 64,
}
