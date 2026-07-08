"""Conformance profile rules (SPEC §5) beyond JSON Schema."""
from __future__ import annotations

from typing import Any


def iter_profile_errors(data: dict[str, Any]) -> list[str]:
    profiles = data.get("profiles") or []
    if not profiles:
        return []

    errors: list[str] = []
    wants_core = (
        "ucp-core" in profiles
        or "ucp-temporal" in profiles
        or "ucp-secure" in profiles
    )

    if wants_core:
        summary = data.get("summary") or {}
        if not summary.get("text"):
            errors.append("ucp-core: summary.text is required")
        for key, source in (data.get("sources") or {}).items():
            if not source.get("system") or not source.get("type") or not source.get("title"):
                errors.append(f"ucp-core: sources[{key}] missing system, type, or title")
        errors.extend(
            f"ucp-core: dangling source {ref}" for ref in _collect_dangling_refs(data)
        )

    if "ucp-secure" in profiles:
        audience = data.get("audience")
        if not audience:
            errors.append("ucp-secure: audience is required")
        else:
            ac = audience.get("access_control") or {}
            if not ac.get("enforced"):
                errors.append("ucp-secure: audience.access_control.enforced must be true")
            if not ac.get("audit_ref"):
                errors.append("ucp-secure: audience.access_control.audit_ref is required")

    return errors


def _collect_dangling_refs(data: dict[str, Any]) -> list[str]:
    known = set((data.get("sources") or {}).keys())
    dangling: list[str] = []

    def collect(keys: list[str] | None, where: str) -> None:
        for key in keys or []:
            if key not in known:
                dangling.append(f"{where}: {key}")

    summary = data.get("summary") or {}
    collect(summary.get("sources"), "summary")
    for section in ("must_know", "constraints", "risks", "recommended_actions"):
        for claim in data.get(section) or []:
            collect(claim.get("sources"), f"{section}[{claim.get('id')}]")
    for decision in data.get("decisions") or []:
        collect(decision.get("sources"), f"decisions[{decision.get('id')}]")
    for conflict in data.get("conflicts") or []:
        for i, position in enumerate(conflict.get("positions") or []):
            collect(
                position.get("sources"),
                f"conflicts[{conflict.get('id')}].positions[{i}]",
            )
    diff = data.get("context_diff") or {}
    for i, change in enumerate(diff.get("changes") or []):
        collect(change.get("sources"), f"context_diff.changes[{i}]")
    for i, event in enumerate(data.get("history") or []):
        collect(event.get("sources"), f"history[{i}]")
    return dangling
