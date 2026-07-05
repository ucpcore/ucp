"""A realistic Jira issue bundle (API v2 shapes, trimmed to fields we read)."""


def user(account_id: str, name: str) -> dict:
    return {"accountId": account_id, "displayName": name}


JIRA_BUNDLE = {
    "base_url": "https://acme.atlassian.net",
    "issue": {
        "key": "PAY-482",
        "fields": {
            "summary": "Payment webhook drops events under load",
            "description": (
                "h2. Description\n\n"
                "When more than ~50 webhook events arrive per second, some are\n"
                "silently dropped.\n\nSteps: fire 100 events, count processed."
            ),
            "status": {"name": "Done"},
            "resolution": {"name": "Fixed"},
            "resolutiondate": "2026-06-20T18:00:00.000+0000",
            "issuetype": {"name": "Bug"},
            "priority": {"name": "Highest"},
            "labels": ["payments", "incident-followup"],
            "duedate": "2026-07-01",
            "fixVersions": [{"name": "2.1"}],
            "reporter": user("a1", "Alice Cooper"),
            "assignee": user("b2", "Bob Dole"),
            "created": "2026-06-01T09:00:00.000+0000",
            "updated": "2026-06-20T18:00:00.000+0000",
            "issuelinks": [
                {
                    "type": {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
                    "inwardIssue": {"key": "INFRA-77",
                                    "fields": {"summary": "Provision idempotency store"}},
                },
                {
                    "type": {"name": "Relates", "inward": "relates to", "outward": "relates to"},
                    "outwardIssue": {"key": "PAY-490",
                                     "fields": {"summary": "Audit all webhook consumers"}},
                },
            ],
            "parent": {"key": "PAY-400", "fields": {"summary": "Payments reliability epic"}},
            "subtasks": [
                {"key": "PAY-483", "fields": {"summary": "Add idempotency key to consumer"}}
            ],
        },
        "changelog": {
            "histories": [
                {
                    "author": user("b2", "Bob Dole"),
                    "created": "2026-06-02T10:00:00.000+0000",
                    "items": [{"field": "status", "fromString": "To Do",
                               "toString": "In Progress"}],
                },
                {
                    "author": user("b2", "Bob Dole"),
                    "created": "2026-06-20T18:00:00.000+0000",
                    "items": [
                        {"field": "status", "fromString": "In Progress", "toString": "Done"},
                        {"field": "resolution", "fromString": None, "toString": "Fixed"},
                        {"field": "Rank", "fromString": "x", "toString": "y"},
                    ],
                },
            ]
        },
    },
    "comments": [
        {
            "id": "9001",
            "author": user("b2", "Bob Dole"),
            "created": "2026-06-02T11:00:00.000+0000",
            "body": "Reproduced. The consumer acks before processing finishes.",
        },
        {
            "id": "9002",
            "author": user("c3", "Carol King"),
            "created": "2026-06-05T12:00:00.000+0000",
            "body": "We decided to switch to at-least-once delivery with an idempotency key.",
        },
    ],
}
