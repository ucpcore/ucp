"""Receipt store analytics and warm-ranking aggregates."""
from ucp_server.receipt_store import ReceiptStore


def _receipt(**kwargs):
    base = {
        "package_id": "jira-kan-1",
        "outcome": "task_completed",
        "claims_cited": [],
        "claims_ignored": [],
    }
    base.update(kwargs)
    return base


def test_analytics_claim_heatmap(tmp_path):
    settings = type("S", (), {"cache_dir": tmp_path})()
    store = ReceiptStore(settings)
    store.append(_receipt(claims_cited=["claim-a"], claims_ignored=["claim-b"]))
    store.append(_receipt(claims_cited=["claim-a", "claim-c"]))

    data = store.analytics(limit=10)
    assert data["total"] == 2
    assert data["claims_cited_total"] == 3
    assert data["claims_ignored_total"] == 1
    top = {row["id"]: row for row in data["claims"]}
    assert top["claim-a"]["cited"] == 2
    assert top["claim-b"]["ignored"] == 1


def test_aggregate_claim_signals_cited_wins(tmp_path):
    settings = type("S", (), {"cache_dir": tmp_path})()
    store = ReceiptStore(settings)
    store.append(_receipt(claims_cited=["x"], claims_ignored=["x"]))
    cited, ignored = store.aggregate_claim_signals()
    assert "x" in cited
    assert "x" not in ignored
