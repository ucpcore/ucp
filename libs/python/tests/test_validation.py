import json

import pytest

import ucp
from tests.conftest import SPEC_DIR, requires_spec


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


@requires_spec
def test_spec_example_validates(example_data):
    ucp.validate(example_data)  # must not raise


@requires_spec
def test_conformance_valid_suite():
    for path in sorted((SPEC_DIR / "conformance" / "valid").glob("*.json")):
        assert ucp.iter_errors(_load(path)) == [], path.name


@requires_spec
def test_conformance_invalid_suite():
    for path in sorted((SPEC_DIR / "conformance" / "invalid").glob("*.json")):
        with pytest.raises(ucp.UCPValidationError):
            ucp.validate(_load(path))


@requires_spec
def test_bundled_schema_matches_spec_schema():
    spec_schema = _load(SPEC_DIR / "schema" / "ucp.schema.json")
    assert ucp.schema() == spec_schema, (
        "bundled schema is out of sync with specs/ucp/schema/ucp.schema.json"
    )


def test_validation_error_messages_are_informative():
    errors = ucp.iter_errors({"ucp_version": "0.1.0"})
    assert errors
    assert any("required" in e for e in errors)
