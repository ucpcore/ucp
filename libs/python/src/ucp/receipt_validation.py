"""JSON Schema validation for Usage Receipt documents (RFC-0007)."""
from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


@lru_cache(maxsize=1)
def receipt_schema() -> dict[str, Any]:
    text = files("ucp").joinpath("schema/usage-receipt.schema.json").read_text(
        encoding="utf-8"
    )
    return json.loads(text)


@lru_cache(maxsize=1)
def _receipt_validator() -> Draft202012Validator:
    return Draft202012Validator(receipt_schema(), format_checker=FormatChecker())


def iter_receipt_errors(data: dict[str, Any]) -> list[str]:
    return [
        f"{'/'.join(str(p) for p in error.absolute_path) or '<root>'}: {error.message}"
        for error in _receipt_validator().iter_errors(data)
    ]


def validate_receipt(data: dict[str, Any]) -> None:
    errors = iter_receipt_errors(data)
    if errors:
        from .validation import UCPValidationError

        raise UCPValidationError(errors)
