"""Canonical CommonMark rendering of a UCP package (SPEC §7).

The rendering is deterministic: the same package always produces the same
prompt. Under a token budget, items are dropped in ascending-salience order
within sections, and sections are dropped in the order of SPEC §7.2 —
``summary``, ``conflicts``, and ``context_diff`` survive longest.
"""
from __future__ import annotations

import math
from copy import deepcopy
from datetime import datetime
from typing import Callable, Optional

from .models import Claim, Package, Source

# Sections whose items may be dropped under a token budget, cheapest first.
DROP_ORDER = (
    "history",
    "related_objects",
    "recommended_actions",
    "risks",
    "constraints",
    "decisions",
    "must_know",
)

_SECTION_TITLES = {
    "must_know": "Must know",
    "constraints": "Constraints",
    "risks": "Risks",
    "recommended_actions": "Recommended actions",
}


def estimate_tokens(text: str) -> int:
    """Fast token estimate (~4 chars per token). Good enough for budgeting."""
    return max(1, math.ceil(len(text) / 4))


def _date(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y-%m-%d") if dt else ""


def _source_labels(keys: list[str], sources: dict[str, Source]) -> str:
    titles = [sources[k].title if k in sources else k for k in keys]
    return ", ".join(titles)


def _claim_line(claim: Claim, sources: dict[str, Source]) -> str:
    label = _source_labels(claim.sources, sources)
    return f"- {claim.text} [source: {label}]"


def _by_salience_desc(items: list) -> list:
    """Descending salience; unspecified salience sorts last, original order kept.

    Works for any item type: models without a salience field (e.g. Event)
    are treated as unspecified.
    """

    def salience(item) -> float:
        value = getattr(item, "salience", None)
        return value if value is not None else -1.0

    return sorted(enumerate(items), key=lambda pair: (-salience(pair[1]), pair[0]))


def _render(pkg: Package) -> str:
    src = pkg.sources
    out: list[str] = []

    ref = pkg.entity.ref
    out.append(f"# Context: {pkg.entity.title}")
    ref_line = f"> {ref.system}/{ref.type} {ref.id}"
    if ref.url:
        ref_line += f" — {ref.url}"
    out.append(ref_line)
    if pkg.entity.status:
        out.append(f"> Status: {pkg.entity.status}")
    out.append("")

    if pkg.context_diff is not None:
        out.append("## What changed")
        out.append(f"Since {_date(pkg.context_diff.since)}:")
        if pkg.context_diff.changes:
            for change in pkg.context_diff.changes:
                when = f"[{_date(change.occurred_at)}] " if change.occurred_at else ""
                out.append(f"- {when}{change.summary}")
        else:
            out.append("- Nothing changed.")
        out.append("")

    if pkg.summary:
        out.append("## Summary")
        out.append(pkg.summary.text)
        out.append("")

    for field in ("must_know", "constraints", "risks"):
        claims: list[Claim] = getattr(pkg, field)
        if claims:
            out.append(f"## {_SECTION_TITLES[field]}")
            for _, claim in _by_salience_desc(claims):
                out.append(_claim_line(claim, src))
            out.append("")

    if pkg.decisions:
        out.append("## Decisions")
        for decision in pkg.decisions:
            line = f"- {decision.decision}"
            if decision.rationale:
                line += f" — {decision.rationale}"
            meta = decision.status + (f", {_date(decision.decided_at)}" if decision.decided_at else "")
            out.append(f"{line} ({meta})")
        out.append("")

    if pkg.conflicts:
        out.append("## Conflicts")
        for conflict in pkg.conflicts:
            out.append(f"- {conflict.description}")
            for position in conflict.positions:
                when = f" ({_date(position.asserted_at)})" if position.asserted_at else ""
                label = _source_labels(position.sources, src)
                out.append(f"  - {position.claim}{when} [source: {label}]")
            if conflict.resolution_hint:
                out.append(f"  - Hint: {conflict.resolution_hint}")
        out.append("")

    if pkg.recommended_actions:
        out.append(f"## {_SECTION_TITLES['recommended_actions']}")
        for _, claim in _by_salience_desc(pkg.recommended_actions):
            out.append(_claim_line(claim, src))
        out.append("")

    if pkg.history:
        out.append("## Timeline")
        for event in sorted(pkg.history, key=lambda e: e.occurred_at):
            out.append(f"- [{_date(event.occurred_at)}] {event.summary}")
        out.append("")

    if pkg.related_objects:
        out.append("## Related")
        for _, related in _by_salience_desc(pkg.related_objects):
            line = f"- {related.title}"
            if related.relation:
                line += f" ({related.relation})"
            if related.reason:
                line += f" — {related.reason}"
            out.append(line)
        out.append("")

    out.append("## Sources")
    for i, (key, source) in enumerate(pkg.sources.items(), start=1):
        line = f"{i}. {source.title}"
        if source.url:
            line += f" — {source.url}"
        out.append(line)

    return "\n".join(out).strip() + "\n"


def render(
    pkg: Package,
    token_budget: Optional[int] = None,
    count_tokens: Callable[[str], int] = estimate_tokens,
) -> str:
    """Render a package to canonical CommonMark, optionally under a token budget."""
    text = _render(pkg)
    if token_budget is None or count_tokens(text) <= token_budget:
        return text

    trimmed = deepcopy(pkg)
    for section in DROP_ORDER:
        while getattr(trimmed, section):
            # Drop the least salient item (ascending salience = end of the
            # descending-ordered list, which is also the render order).
            ordered = [item for _, item in _by_salience_desc(getattr(trimmed, section))]
            ordered.pop()
            setattr(trimmed, section, ordered)
            text = _render(trimmed)
            if count_tokens(text) <= token_budget:
                return text
    # Budget cannot be met by dropping optional sections; the protected core
    # (summary, conflicts, context_diff) is returned as-is by design.
    return text
