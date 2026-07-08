"""Map a document connector bundle to a valid Universal Context Package.

Index-only path: the engine stores parsed text from Confluence, Drive or
Yandex Disk; ucp-server serves pre-indexed bundles (no live fetch here).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .build import GENERATOR, SPEC_VERSION, _excerpt, _first_paragraph, _hash, _iso

_OBJECT_TYPE = {
    "confluence": "page",
    "gdrive": "file",
    "yandex_disk": "file",
}

# Docling labels that are body copy — already in content_text; skip as must_know rows.
_DOC_NOISE_SECTION_LABELS = frozenset({
    "text",
    "paragraph",
    "picture",
    "figure",
    "checkbox_selected",
    "checkbox_unselected",
    "form",
    "key_value_region",
    "page_footer",
    "page_header",
    "footnote",
})


def _author_actor(author: Optional[dict]) -> Optional[dict]:
    if not author:
        return None
    if email := author.get("email"):
        return {"id": email, "display_name": email.split("@", 1)[0]}
    if author_id := author.get("id"):
        return {"id": str(author_id), "display_name": str(author_id)}
    return None


def build_document_package(
    bundle: dict[str, Any],
    since: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build a UCP dict from an engine document bundle (Confluence / Drive / Yandex)."""
    source = bundle["source_system"]
    external_id = bundle["external_id"]
    object_type = bundle.get("object_type") or _OBJECT_TYPE.get(source, "document")
    title = bundle.get("title") or external_id
    url = bundle.get("url")
    content_text = bundle.get("content_text") or ""
    generated_at = (now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")

    source_key = "document"
    sources: dict[str, dict] = {
        source_key: {
            "system": source,
            "type": object_type,
            "title": title,
            "url": url,
            "author": _author_actor(bundle.get("author")),
            "created_at": _iso(bundle.get("created_at")),
            "updated_at": _iso(bundle.get("updated_at")),
            "content_hash": bundle.get("content_hash") or _hash(content_text),
            "retrieved_at": generated_at,
            "excerpt": _excerpt(content_text),
        }
    }

    must_know: list[dict] = []

    def claim(cid: str, text: str, salience: float, **extra: Any) -> None:
        must_know.append(
            {
                "id": cid,
                "text": text,
                "salience": salience,
                "salience_method": "producer",
                "sources": [source_key],
                **extra,
            }
        )

    claim("title", f"Title: {title}", 0.95, kind="fact")
    parent = bundle.get("parent") or {}
    if parent.get("name"):
        claim("parent", f"Parent: {parent['name']}", 0.75, kind="fact")
    if mime := bundle.get("mime_type"):
        claim("mime", f"Format: {mime}", 0.55, kind="fact")
    parser = (bundle.get("parsed") or {}).get("parser")
    if parser:
        claim("parser", f"Parsed with: {parser}", 0.5, kind="fact")

    for idx, section in enumerate((bundle.get("parsed") or {}).get("sections") or []):
        body = (section.get("text") or "").strip()
        if not body:
            continue
        label_raw = section.get("title") or f"section-{idx + 1}"
        label_norm = str(label_raw).lower().replace("-", "_")
        if label_norm in _DOC_NOISE_SECTION_LABELS:
            continue
        claim(
            f"section-{idx + 1}",
            f"{label_raw}: {_excerpt(body) or body[:400]}",
            0.7,
            kind="fact",
        )

    if content_text.strip():
        claim(
            "content",
            _excerpt(content_text) or content_text[:500],
            0.9,
            kind="fact",
        )

    history: list[dict] = []
    if created := bundle.get("created_at"):
        history.append(
            {
                "occurred_at": created,
                "summary": f"Document created ({title})",
                "actor": _author_actor(bundle.get("author")),
                "sources": [source_key],
            }
        )
    if updated := bundle.get("updated_at"):
        if updated != bundle.get("created_at"):
            history.append(
                {
                    "occurred_at": updated,
                    "summary": f"Document updated ({title})",
                    "actor": _author_actor(bundle.get("author")),
                    "sources": [source_key],
                }
            )

    diff_changes: list[dict] = []
    if since:
        for entry in history:
            if entry["occurred_at"] > since:
                diff_changes.append(
                    {
                        "type": "updated",
                        "summary": entry["summary"],
                        "occurred_at": entry["occurred_at"],
                        "actor": entry.get("actor"),
                        "sources": [source_key],
                    }
                )

    profiles = ["ucp-core"]
    package: dict[str, Any] = {
        "ucp_version": SPEC_VERSION,
        "id": f"urn:uuid:{uuid.uuid4()}",
        "generated_at": generated_at,
        "generator": GENERATOR,
        "profiles": profiles,
        "entity": {
            "ref": {
                "system": source,
                "type": object_type,
                "id": external_id,
                "url": url,
            },
            "title": title,
            "status": "indexed",
        },
        "summary": {
            "text": _first_paragraph(content_text, title),
            "sources": [source_key],
        },
        "must_know": must_know,
        "decisions": [],
        "conflicts": [],
        "history": history,
        "dependencies": [],
        "related_objects": [],
        "sources": sources,
    }
    if since:
        profiles.append("ucp-temporal")
        package["context_diff"] = {"since": since, "changes": diff_changes}
    return _merge_bundle_enrichment(package, bundle)


def _merge_bundle_enrichment(package: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    """Merge optional index metadata: extra sources, related objects, document conflicts."""
    for key, src in (bundle.get("extra_sources") or {}).items():
        if isinstance(src, dict):
            package["sources"][key] = src

    existing_related = {
        (r.get("ref") or {}).get("id") for r in package.get("related_objects") or [] if isinstance(r, dict)
    }
    for rel in bundle.get("related_objects") or []:
        if not isinstance(rel, dict):
            continue
        rid = (rel.get("ref") or {}).get("id")
        if rid and rid in existing_related:
            continue
        package.setdefault("related_objects", []).append(rel)
        if rid:
            existing_related.add(rid)

    existing_conflict_ids = {c["id"] for c in package.get("conflicts", []) if isinstance(c, dict) and c.get("id")}
    for conflict in bundle.get("related_conflicts") or []:
        if not isinstance(conflict, dict) or not conflict.get("id"):
            continue
        if conflict["id"] in existing_conflict_ids:
            continue
        package.setdefault("conflicts", []).append(conflict)
        existing_conflict_ids.add(conflict["id"])

    return package


def llm_docs(bundle: dict[str, Any], generated_at: str) -> list[dict[str, Any]]:
    """Full-text documents for optional LLM enhancement (see ``llm.py``)."""
    source = bundle["source_system"]
    object_type = bundle.get("object_type") or _OBJECT_TYPE.get(source, "document")
    title = bundle.get("title") or bundle["external_id"]
    content_text = bundle.get("content_text") or ""
    return [
        {
            "key": "document",
            "label": f"{title} ({source})",
            "text": content_text,
            "source": {
                "system": source,
                "type": object_type,
                "title": title,
                "url": bundle.get("url"),
                "author": _author_actor(bundle.get("author")),
                "created_at": _iso(bundle.get("created_at")),
                "updated_at": _iso(bundle.get("updated_at")),
                "content_hash": bundle.get("content_hash") or _hash(content_text),
                "retrieved_at": generated_at,
                "excerpt": _excerpt(content_text),
            },
        }
    ]
