"""ucp — reference library for the Universal Context Package specification.

Spec: https://github.com/contextos/ucp (v0.1.0-draft)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Union

from .models import (
    AccessControl,
    Actor,
    Audience,
    Budget,
    Change,
    Claim,
    Conflict,
    ConflictPosition,
    ContextDiff,
    Decision,
    Entity,
    EntityRef,
    Event,
    Generator,
    Package,
    RelatedObject,
    Source,
    Summary,
)
from .render import estimate_tokens, render
from .validation import UCPValidationError, iter_errors, schema, validate

__version__ = "0.1.0"

SPEC_VERSION = "0.1.0"


def loads(text: str, *, validate_schema: bool = True) -> Package:
    """Parse a UCP document from a JSON string."""
    data = json.loads(text)
    if validate_schema:
        validate(data)
    return Package.model_validate(data)


def load(path: Union[str, Path], *, validate_schema: bool = True) -> Package:
    """Load a UCP document from a ``.ucp.json`` file."""
    return loads(Path(path).read_text(encoding="utf-8"), validate_schema=validate_schema)


def dumps(pkg: Package, *, indent: int = 2) -> str:
    """Serialize a package back to JSON (unknown fields preserved)."""
    return pkg.model_dump_json(indent=indent, exclude_none=True, by_alias=True)


__all__ = [
    "SPEC_VERSION",
    "AccessControl",
    "Actor",
    "Audience",
    "Budget",
    "Change",
    "Claim",
    "Conflict",
    "ConflictPosition",
    "ContextDiff",
    "Decision",
    "Entity",
    "EntityRef",
    "Event",
    "Generator",
    "Package",
    "RelatedObject",
    "Source",
    "Summary",
    "UCPValidationError",
    "dumps",
    "estimate_tokens",
    "iter_errors",
    "load",
    "loads",
    "render",
    "schema",
    "validate",
]
