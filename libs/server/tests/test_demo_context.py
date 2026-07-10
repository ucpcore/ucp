"""Demo context for onboarding."""
import json

from ucp_server.demo_context import build_demo_context

from .conftest import make_settings


def test_demo_context_benchmark(tmp_path):
    settings = make_settings(tmp_path)
    cache = type("C", (), {"find": lambda self, pid: None})()
    data = build_demo_context(settings, "alice", cache)
    assert data["comparison"]["mode"] == "benchmark"
    assert data["comparison"]["raw_tokens"] == 18500
    assert data["default_view"] == "benchmark"
    assert "benchmark" in data["comparisons"]
    assert "last" not in data["comparisons"]
    assert data["indexed_refs"] == []
    assert "cursor" in data["agents"]
    assert "claude_code" in data["agents"]


def test_demo_context_last_and_total(tmp_path):
    settings = make_settings(tmp_path)
    savings_path = settings.cache_dir / "analytics" / "token_savings.jsonl"
    savings_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "principal": "alice",
            "ref": "acme/rocket#42",
            "source": "github",
            "package_id": "pkg-1",
            "raw_tokens": 9000,
            "ucp_tokens": 800,
            "tokens_saved": 8200,
            "reduction_pct": 91,
        },
        {
            "principal": "alice",
            "ref": "acme/rocket#43",
            "source": "github",
            "package_id": "pkg-2",
            "raw_tokens": 5000,
            "ucp_tokens": 400,
            "tokens_saved": 4600,
            "reduction_pct": 92,
        },
    ]
    savings_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    cache = type("C", (), {"find": lambda self, pid: None})()
    data = build_demo_context(settings, "alice", cache)

    assert data["default_view"] == "last"
    assert data["comparison"]["mode"] == "yours"
    assert data["comparison"]["ref"] == "acme/rocket#43"
    assert data["comparisons"]["last"]["tokens_saved"] == 4600
    assert data["comparisons"]["total"]["raw_tokens"] == 14000
    assert data["comparisons"]["total"]["tokens_saved"] == 12800
    assert data["comparisons"]["total"]["packages"] == 2


def test_demo_context_indexed_refs(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    cache = type("C", (), {"find": lambda self, pid: None})()

    def fake_indexed_refs(_settings):
        return [
            {
                "ref": "acme/rocket#42",
                "source": "github",
                "title": "Fix launch",
                "updated_at": "2026-07-09T12:00:00Z",
            }
        ]

    monkeypatch.setattr("ucp_server.demo_context._indexed_refs", fake_indexed_refs)
    data = build_demo_context(settings, "alice", cache)
    assert data["indexed_refs"][0]["ref"] == "acme/rocket#42"
    assert data["suggested_ref"] == "acme/rocket#42"
