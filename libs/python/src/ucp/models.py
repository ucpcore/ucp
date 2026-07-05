"""Typed models for Universal Context Packages (SPEC §4).

All models tolerate unknown fields (``extra="allow"``) to honor the
must-ignore rule (SPEC §6.1): a package produced by a newer spec version
must parse, with unknown fields preserved on the model instance.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class _UCPModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Actor(_UCPModel):
    id: str
    display_name: Optional[str] = None
    role: Optional[str] = None


class Generator(_UCPModel):
    name: str
    version: Optional[str] = None
    url: Optional[str] = None


class EntityRef(_UCPModel):
    system: str
    type: str
    id: str
    url: Optional[str] = None


class Entity(_UCPModel):
    ref: EntityRef
    title: str
    status: Optional[str] = None
    assignee: Optional[Actor] = None
    attributes: Optional[dict[str, Any]] = None


class Summary(_UCPModel):
    text: str
    sources: list[str] = Field(default_factory=list)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)


class Claim(_UCPModel):
    id: str
    text: str
    sources: list[str] = Field(min_length=1)
    kind: Optional[str] = None
    salience: Optional[float] = Field(default=None, ge=0, le=1)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    asserted_at: Optional[datetime] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    tags: list[str] = Field(default_factory=list)


class Decision(_UCPModel):
    id: str
    decision: str
    status: Literal["proposed", "accepted", "superseded", "rejected"]
    sources: list[str] = Field(min_length=1)
    rationale: Optional[str] = None
    decided_by: Optional[Actor] = None
    decided_at: Optional[datetime] = None
    supersedes: Optional[str] = None


class ConflictPosition(_UCPModel):
    claim: str
    sources: list[str] = Field(min_length=1)
    asserted_at: Optional[datetime] = None


class Conflict(_UCPModel):
    id: str
    description: str
    positions: list[ConflictPosition] = Field(min_length=2)
    resolution_hint: Optional[str] = None
    severity: Optional[Literal["low", "medium", "high"]] = None


class Change(_UCPModel):
    type: Literal["added", "updated", "removed", "status_changed"]
    summary: str
    target: Optional[str] = None
    occurred_at: Optional[datetime] = None
    actor: Optional[Actor] = None
    sources: list[str] = Field(default_factory=list)


class ContextDiff(_UCPModel):
    since: datetime
    changes: list[Change]
    baseline: Optional[str] = None


class Event(_UCPModel):
    occurred_at: datetime
    summary: str
    actor: Optional[Actor] = None
    sources: list[str] = Field(default_factory=list)


class RelatedObject(_UCPModel):
    ref: EntityRef
    title: str
    relation: Optional[str] = None
    salience: Optional[float] = Field(default=None, ge=0, le=1)
    reason: Optional[str] = None


class Source(_UCPModel):
    system: str
    type: str
    title: str
    url: Optional[str] = None
    author: Optional[Actor] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    content_hash: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    trust: Optional[float] = Field(default=None, ge=0, le=1)
    excerpt: Optional[str] = None


class AccessControl(_UCPModel):
    enforced: bool
    mechanism: Optional[str] = None
    checked_at: Optional[datetime] = None
    audit_ref: Optional[str] = None


class Audience(_UCPModel):
    principal: Actor
    access_control: Optional[AccessControl] = None


class Budget(_UCPModel):
    token_estimate: Optional[int] = Field(default=None, ge=0)


class Package(_UCPModel):
    ucp_version: str
    id: str
    generated_at: datetime
    generator: Generator
    entity: Entity
    sources: dict[str, Source] = Field(min_length=1)

    profiles: list[str] = Field(default_factory=list)
    language: Optional[str] = None
    audience: Optional[Audience] = None
    situation: Optional[str] = None
    summary: Optional[Summary] = None
    must_know: list[Claim] = Field(default_factory=list)
    constraints: list[Claim] = Field(default_factory=list)
    risks: list[Claim] = Field(default_factory=list)
    recommended_actions: list[Claim] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    context_diff: Optional[ContextDiff] = None
    history: list[Event] = Field(default_factory=list)
    dependencies: list[EntityRef] = Field(default_factory=list)
    related_objects: list[RelatedObject] = Field(default_factory=list)
    budget: Optional[Budget] = None
    extensions: dict[str, Any] = Field(default_factory=dict)

    def verify_references(self) -> list[str]:
        """Return dangling source keys referenced anywhere in the package.

        The ucp-core profile requires every referenced key to exist in the
        ``sources`` registry. An empty list means the package is clean.
        """
        known = set(self.sources)
        dangling: list[str] = []

        def collect(keys: list[str], where: str) -> None:
            for key in keys:
                if key not in known:
                    dangling.append(f"{where}: {key}")

        if self.summary:
            collect(self.summary.sources, "summary")
        for section_name in ("must_know", "constraints", "risks", "recommended_actions"):
            for claim in getattr(self, section_name):
                collect(claim.sources, f"{section_name}[{claim.id}]")
        for decision in self.decisions:
            collect(decision.sources, f"decisions[{decision.id}]")
        for conflict in self.conflicts:
            for i, position in enumerate(conflict.positions):
                collect(position.sources, f"conflicts[{conflict.id}].positions[{i}]")
        if self.context_diff:
            for i, change in enumerate(self.context_diff.changes):
                collect(change.sources, f"context_diff.changes[{i}]")
        for i, event in enumerate(self.history):
            collect(event.sources, f"history[{i}]")
        return dangling

    def render(self, token_budget: Optional[int] = None, **kwargs: Any) -> str:
        from .render import render

        return render(self, token_budget=token_budget, **kwargs)
