"""JSON Schema validation for UCP documents (SPEC schema, draft 2020-12)."""
from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .profiles import iter_profile_errors


class UCPValidationError(ValueError):
    """Raised when a document does not conform to the UCP schema."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


@lru_cache(maxsize=1)
def schema() -> dict[str, Any]:
    """The bundled UCP JSON Schema."""
    text = files("ucp").joinpath("schema/ucp.schema.json").read_text(encoding="utf-8")
    return json.loads(text)


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    return Draft202012Validator(schema(), format_checker=FormatChecker())


def iter_errors(data: dict[str, Any]) -> list[str]:
    """Schema + profile errors (empty = valid)."""
    schema_errors = [
        f"{'/'.join(str(p) for p in error.absolute_path) or '<root>'}: {error.message}"
        for error in _validator().iter_errors(data)
    ]
    if schema_errors:
        return schema_errors
    return iter_profile_errors(data)


def validate(data: dict[str, Any]) -> None:
    """Validate ``data`` against the UCP schema and declared profiles."""
    errors = iter_errors(data)
    if errors:
        raise UCPValidationError(errors)
