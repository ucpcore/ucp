import json
import shutil
from pathlib import Path

import pytest

import ucp_mcp.server as server
from ucp_mcp.store import PackageStore

# Works in both layouts: workspace (specs/ucp) and public monorepo (root).
_root = Path(__file__).parents[3]
_spec_dir = next(
    (c for c in (_root / "specs" / "ucp", _root) if (c / "examples").exists()),
    _root,
)
SPEC_EXAMPLE = _spec_dir / "examples" / "jira-task.ucp.json"


@pytest.fixture()
def store(tmp_path, monkeypatch):
    if not SPEC_EXAMPLE.exists():
        pytest.skip("spec example not available")
    shutil.copy(SPEC_EXAMPLE, tmp_path / "jira-task.ucp.json")
    s = PackageStore(tmp_path)
    monkeypatch.setattr(server, "_store", s)
    return s


def test_list_contexts(store):
    items = json.loads(server.list_contexts())
    assert len(items) == 1
    assert items[0]["entity_id"] == "PAY-482"
    assert items[0]["system"] == "jira"
    assert "ucp-secure" in items[0]["profiles"]


def test_get_context_by_id_returns_valid_ucp(store):
    import ucp

    data = json.loads(server.get_context("PAY-482"))
    ucp.validate(data)  # round-trip must stay schema-valid
    assert data["entity"]["ref"]["id"] == "PAY-482"


def test_find_by_url_and_title_fragment(store):
    by_url = server.get_context("https://acme.atlassian.net/browse/PAY-482")
    by_title = server.get_context("payment webhooks")
    assert json.loads(by_url)["id"] == json.loads(by_title)["id"]


def test_get_context_markdown_with_budget(store):
    import ucp

    full = server.get_context_markdown("PAY-482")
    text = server.get_context_markdown("PAY-482", token_budget=450)
    assert text.startswith("# Context: Migrate payment webhooks to v2 API")
    assert ucp.estimate_tokens(text) <= 450
    assert len(text) < len(full)

    # An unreachable budget still returns the protected core (SPEC §7.2),
    # never an empty or broken document.
    tiny = server.get_context_markdown("PAY-482", token_budget=10)
    assert "## Summary" in tiny
    assert "## Conflicts" in tiny


def test_not_found_lists_available(store):
    answer = server.get_context("NOPE-1")
    assert "No context package found" in answer
    assert "PAY-482" in answer


def test_store_picks_up_changes(store, tmp_path):
    (tmp_path / "jira-task.ucp.json").unlink()
    assert server.get_context("PAY-482").startswith("No context package found")


def test_invalid_package_is_skipped_not_fatal(store, tmp_path):
    (tmp_path / "broken.ucp.json").write_text('{"ucp_version": "0.1.0"}')
    items = json.loads(server.list_contexts())
    assert len(items) == 1  # broken file ignored, valid one still served
