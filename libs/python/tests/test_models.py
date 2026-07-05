import pydantic
import pytest

import ucp
from tests.conftest import requires_spec

MINIMAL = {
    "ucp_version": "0.1.0",
    "id": "urn:uuid:00000000-0000-4000-8000-00000000000a",
    "generated_at": "2026-07-05T12:00:00Z",
    "generator": {"name": "test"},
    "entity": {
        "ref": {"system": "jira", "type": "issue", "id": "X-1"},
        "title": "Test",
    },
    "sources": {"s": {"system": "jira", "type": "issue", "title": "X-1"}},
}


@requires_spec
def test_parse_spec_example(example_data):
    pkg = ucp.Package.model_validate(example_data)
    assert pkg.entity.ref.id == "PAY-482"
    assert pkg.must_know[0].sources == ["src-3"]
    assert pkg.decisions[0].status == "accepted"
    assert pkg.audience.access_control.enforced is True
    assert pkg.verify_references() == []


def test_unknown_fields_are_preserved_not_rejected():
    data = {**MINIMAL, "field_from_the_future": {"x": 1}}
    pkg = ucp.Package.model_validate(data)
    assert pkg.field_from_the_future == {"x": 1}
    assert '"field_from_the_future"' in ucp.dumps(pkg)


def test_claim_without_sources_is_rejected_by_models():
    with pytest.raises(pydantic.ValidationError):
        ucp.Claim(id="c1", text="no provenance")


def test_verify_references_finds_dangling_keys():
    data = {
        **MINIMAL,
        "must_know": [{"id": "mk-1", "text": "t", "sources": ["missing-key"]}],
    }
    pkg = ucp.Package.model_validate(data)
    dangling = pkg.verify_references()
    assert dangling == ["must_know[mk-1]: missing-key"]


def test_loads_validates_by_default():
    import json

    bad = {**MINIMAL}
    del bad["entity"]
    with pytest.raises(ucp.UCPValidationError):
        ucp.loads(json.dumps(bad))
