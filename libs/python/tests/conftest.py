import json
from pathlib import Path

import pytest

# Works in both layouts: the workspace (spec under specs/ucp) and the
# public monorepo (spec files at the repository root).
_root = Path(__file__).parents[3]
_candidates = [_root / "specs" / "ucp", _root]
SPEC_DIR = next(
    (c for c in _candidates if (c / "schema" / "ucp.schema.json").exists()),
    _candidates[0],
)

requires_spec = pytest.mark.skipif(
    not SPEC_DIR.exists(), reason="spec repository layout not available"
)


@pytest.fixture()
def example_data() -> dict:
    path = SPEC_DIR / "examples" / "jira-task.ucp.json"
    if not path.exists():
        pytest.skip("spec example not available")
    return json.loads(path.read_text(encoding="utf-8"))
