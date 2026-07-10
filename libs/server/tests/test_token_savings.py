"""Token savings analytics."""
import ucp

from ucp_server.token_savings import TokenSavingsStore, estimate_raw_tokens

from .conftest import make_settings


def test_estimate_raw_tokens_github():
    bundle = {
        "issue": {"title": "Bug", "body": "A" * 4000},
        "comments": [{"body": "B" * 2000}],
        "linked_pulls": [],
    }
    raw = estimate_raw_tokens("github", bundle)
    assert raw > 1000


def test_token_savings_summary(tmp_path):
    settings = make_settings(tmp_path)
    store = TokenSavingsStore(settings)
    store.record(
        principal="alice",
        source="github",
        ref="acme/app#1",
        package_id="github-acme-app-1",
        ucp_tokens=1200,
        raw_tokens=18000,
    )
    summary = store.summary("alice")
    assert summary["packages"] == 1
    assert summary["tokens_saved"] == 16800
    assert summary["avg_reduction_pct"] > 90
