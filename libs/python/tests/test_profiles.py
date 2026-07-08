"""Profile conformance beyond JSON Schema."""
from __future__ import annotations

import pytest

import ucp


def test_ucp_secure_requires_audience():
    doc = {
        "ucp_version": "0.1.1",
        "id": "urn:uuid:1",
        "generated_at": "2026-07-08T12:00:00Z",
        "generator": {"name": "t"},
        "profiles": ["ucp-secure"],
        "entity": {
            "ref": {"system": "jira", "type": "issue", "id": "X"},
            "title": "x",
        },
        "summary": {"text": "s"},
        "sources": {"src-1": {"system": "jira", "type": "issue", "title": "x"}},
    }
    assert ucp.iter_profile_errors(doc)
    with pytest.raises(ucp.UCPValidationError) as exc:
        ucp.validate(doc)
    assert any("ucp-secure" in e for e in exc.value.errors)


def test_salience_method_validates():
    doc = {
        "ucp_version": "0.1.1",
        "id": "urn:uuid:2",
        "generated_at": "2026-07-08T12:00:00Z",
        "generator": {"name": "t"},
        "entity": {
            "ref": {"system": "jira", "type": "issue", "id": "X"},
            "title": "x",
        },
        "must_know": [
            {
                "id": "c1",
                "text": "fact",
                "salience_method": "producer",
                "sources": ["src-1"],
            }
        ],
        "sources": {"src-1": {"system": "jira", "type": "issue", "title": "x"}},
    }
    ucp.validate(doc)
