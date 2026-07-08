"""Tests for document bundle → UCP mapping."""
from __future__ import annotations

import copy
from datetime import datetime, timezone

import ucp
from ucp_gen import build_document_package
from ucp_gen.build_document import llm_docs

CONFLUENCE_PAGE_BUNDLE = {
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
    "content_hash": "sha256:fixture",
}

GDRIVE_FILE_BUNDLE = {
    "source_system": "gdrive",
    "object_type": "file",
    "external_id": "1abcXYZ",
    "title": "Product Requirements.pdf",
    "url": "https://drive.google.com/file/d/1abcXYZ/view",
    "parent": {"type": "folder", "id": "folder-root", "name": "Drive folder folder-root"},
    "author": {"email": "pm@example.com", "id": "owner1"},
    "created_at": "2026-02-01T09:00:00.000Z",
    "updated_at": "2026-05-20T11:00:00.000Z",
    "content_text": "PRD section 1: MVP scope includes Jira, Confluence, GitHub and Drive.",
    "content_hash": "sha256:gdrive-fixture",
    "mime_type": "application/pdf",
}


def _build(bundle: dict, **kwargs):
    return build_document_package(
        copy.deepcopy(bundle),
        now=datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc),
        **kwargs,
    )


def test_confluence_document_package_validates():
    pkg = ucp.Package.model_validate(_build(CONFLUENCE_PAGE_BUNDLE))
    assert pkg.entity.ref.system == "confluence"
    assert pkg.entity.ref.id == "DOCS:123456"
    assert pkg.summary.text
    assert any(c.id == "title" for c in pkg.must_know)


def test_gdrive_document_package_has_content_claim():
    data = _build(GDRIVE_FILE_BUNDLE)
    assert data["entity"]["ref"]["system"] == "gdrive"
    assert any(item["id"] == "content" for item in data["must_know"])
    assert data["sources"]["document"]["excerpt"]


def test_document_context_diff_since():
    data = _build(CONFLUENCE_PAGE_BUNDLE, since="2026-06-01T00:00:00Z")
    assert "ucp-temporal" in data["profiles"]
    assert data["context_diff"]["since"] == "2026-06-01T00:00:00Z"


def test_document_llm_docs_key_matches_package():
    data = _build(CONFLUENCE_PAGE_BUNDLE)
    docs = llm_docs(CONFLUENCE_PAGE_BUNDLE, data["generated_at"])
    assert len(docs) == 1
    assert docs[0]["key"] == "document"
    assert "ingestion pipeline" in docs[0]["text"]
    assert data["sources"]["document"]["system"] == "confluence"


def test_document_related_conflicts_merge():
    bundle = copy.deepcopy(CONFLUENCE_PAGE_BUNDLE)
    bundle["extra_sources"] = {
        "alt-doc": {
            "system": "confluence",
            "type": "page",
            "title": "PRD depth appendix",
            "url": "https://example.atlassian.net/wiki/spaces/DOCS/pages/999",
            "content_hash": "sha256:bbb",
            "retrieved_at": "2026-07-07T00:00:00.000Z",
            "excerpt": "depth 3 for epics",
        },
    }
    bundle["related_objects"] = [
        {
            "ref": {"system": "confluence", "type": "page", "id": "DOCS:999"},
            "relation": "contradicts",
            "title": "PRD depth appendix",
        },
    ]
    bundle["related_conflicts"] = [
        {
            "id": "conflict-depth",
            "description": "PRD and RFC disagree on graph depth.",
            "positions": [
                {"claim": "Depth is 2.", "sources": ["document"]},
                {"claim": "Depth is 3.", "sources": ["alt-doc"]},
            ],
            "severity": "medium",
        },
    ]
    data = _build(bundle)
    assert "alt-doc" in data["sources"]
    assert len(data["related_objects"]) == 1
    assert len(data["conflicts"]) == 1
    assert data["conflicts"][0]["id"] == "conflict-depth"
    ucp.Package.model_validate(data)


def test_docling_text_sections_not_duplicated_in_must_know():
    bundle = copy.deepcopy(GDRIVE_FILE_BUNDLE)
    bundle["parsed"] = {
        "parser": "docling",
        "sections": [
            {"title": "text", "text": "Прокурору г. Сочи"},
            {"title": "text", "text": "Жалоба"},
            {"title": "section_header", "text": "На бездействие РОСП"},
        ],
    }
    data = _build(bundle)
    texts = [c["text"] for c in data["must_know"]]
    assert not any(t.startswith("text:") for t in texts)
    assert any("section_header:" in t for t in texts)
    assert any(c["id"] == "content" for c in data["must_know"])
