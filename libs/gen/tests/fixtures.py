"""A realistic GitHub issue bundle (trimmed to the fields ucp-gen reads)."""


def user(login: str) -> dict:
    return {"login": login}


BUNDLE = {
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
        "body": (
            "When more than ~50 webhook events arrive per second, some are\n"
            "silently dropped.\n\n"
            "Steps to reproduce:\n1. Fire 100 events\n2. Count processed"
        ),
        "assignee": user("bob"),
        "assignees": [user("bob")],
        "labels": [{"name": "bug"}, {"name": "priority:high"}],
        "milestone": {"title": "v2.1", "due_on": "2026-07-01T00:00:00Z"},
    },
    "comments": [
        {
            "id": 100,
            "user": user("bob"),
            "created_at": "2026-06-02T10:00:00Z",
            "html_url": "https://github.com/acme/rocket/issues/42#issuecomment-100",
            "body": "Reproduced. The consumer ack's before processing finishes.",
        },
        {
            "id": 101,
            "user": user("carol"),
            "created_at": "2026-06-05T12:00:00Z",
            "html_url": "https://github.com/acme/rocket/issues/42#issuecomment-101",
            "body": "We decided to switch to at-least-once delivery with an idempotency key.",
        },
    ],
    "timeline": [
        {"event": "labeled", "created_at": "2026-06-01T09:05:00Z",
         "actor": user("alice"), "label": {"name": "bug"}},
        {"event": "assigned", "created_at": "2026-06-01T09:10:00Z",
         "actor": user("alice"), "assignee": user("bob")},
        {"event": "commented", "created_at": "2026-06-02T10:00:00Z", "actor": user("bob")},
        {"event": "cross-referenced", "created_at": "2026-06-10T08:00:00Z",
         "actor": user("bob"),
         "source": {"issue": {"number": 55, "pull_request": {},
                              "repository": {"full_name": "acme/rocket"}}}},
        {"event": "closed", "created_at": "2026-06-20T18:00:00Z", "actor": user("bob")},
    ],
    "linked_pulls": [
        {
            "number": 55,
            "title": "Make webhook consumer idempotent",
            "state": "closed",
            "merged_at": "2026-06-20T17:55:00Z",
            "merged_by": user("carol"),
            "html_url": "https://github.com/acme/rocket/pull/55",
            "user": user("bob"),
            "created_at": "2026-06-10T08:00:00Z",
            "updated_at": "2026-06-20T17:55:00Z",
            "body": "Adds idempotency keys so redelivered events are no-ops.",
        }
    ],
}
