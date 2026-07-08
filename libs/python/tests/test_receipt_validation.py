"""Tests for Usage Receipt schema validation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import ucp

SPEC_DIR = Path(__file__).resolve().parents[3] / "specs" / "ucp"


@pytest.fixture()
def minimal_receipt():
    return json.loads(
        (SPEC_DIR / "conformance/receipt/valid/minimal.receipt.json").read_text(
            encoding="utf-8"
        )
    )


def test_receipt_conformance_valid(minimal_receipt):
    ucp.validate_receipt(minimal_receipt)


def test_receipt_conformance_invalid():
    path = SPEC_DIR / "conformance/receipt/invalid/bad-outcome.receipt.json"
    with pytest.raises(ucp.UCPValidationError):
        ucp.validate_receipt(json.loads(path.read_text(encoding="utf-8")))


def test_bundled_receipt_schema_matches_spec():
    spec = json.loads(
        (SPEC_DIR / "schema/usage-receipt.schema.json").read_text(encoding="utf-8")
    )
    assert ucp.receipt_schema() == spec
