import copy
import json
from datetime import datetime, timezone

import pytest
import ucp

import ucp_gen.llm as llm_mod
from ucp_gen.build import build_package, llm_docs
from ucp_gen.build_document import llm_docs as document_llm_docs
from ucp_gen import build_document_package
from ucp_gen.llm import LLMConfig, LLMError, enhance

from .fixtures import BUNDLE
from .test_build_document import CONFLUENCE_PAGE_BUNDLE

NOW = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
CONFIG = LLMConfig(base_url="http://llm.test/v1", api_key="k", model="test-model")

LLM_ANSWER = {
    "summary": "Webhook events are dropped under load because the consumer acks "
               "before processing. The team switched to at-least-once delivery "
               "with idempotency keys, shipped in PR #55.",
    "key_sources": ["comment-100", "pr-55"],
    "decisions": [
        {"decision": "Use at-least-once delivery with idempotency keys",
         "status": "accepted", "source": "comment-101"}
    ],
    "conflicts": [
        {"description": "Ack timing disagreement",
         "positions": [
             {"claim": "Ack early keeps latency low", "source": "comment-100"},
             {"claim": "Ack only after processing", "source": "comment-101"},
         ]}
    ],
}


@pytest.fixture
def package_and_docs():
    bundle = copy.deepcopy(BUNDLE)
    package = build_package(bundle, now=NOW)
    return package, llm_docs(bundle, package["generated_at"])


def fake_chat(answer):
    def _fake(config, prompt):
        assert "[issue]" in prompt  # docs made it into the prompt
        return "```json\n" + json.dumps(answer) + "\n```"
    return _fake


def test_enhanced_package_is_valid_and_enriched(monkeypatch, package_and_docs):
    package, docs = package_and_docs
    monkeypatch.setattr(llm_mod, "_chat", fake_chat(LLM_ANSWER))

    enhanced = enhance(package, docs, CONFIG)
    ucp.validate(enhanced)
    pkg = ucp.Package.model_validate(enhanced)
    assert pkg.verify_references() == []

    assert pkg.summary.text.startswith("Webhook events are dropped")
    assert pkg.summary.confidence == 0.7
    assert any(d.id == "decision-llm-0" and d.status == "accepted" for d in pkg.decisions)
    assert len(pkg.conflicts) == 1
    assert enhanced["generator"]["llm_model"] == "test-model"


def test_key_sources_boost_salience(monkeypatch, package_and_docs):
    package, docs = package_and_docs
    before = {c["id"]: c["salience"] for c in package["must_know"]}
    monkeypatch.setattr(llm_mod, "_chat", fake_chat(LLM_ANSWER))

    enhanced = enhance(package, docs, CONFIG)
    boosted = next(c for c in enhanced["must_know"] if "comment-100" in c["sources"])
    assert boosted["salience"] > before[boosted["id"]]


def test_hallucinated_sources_are_dropped(monkeypatch, package_and_docs):
    package, docs = package_and_docs
    answer = {
        "summary": "ok",
        "key_sources": ["comment-99999"],
        "decisions": [{"decision": "x", "status": "accepted", "source": "made-up"}],
        "conflicts": [{"description": "d", "positions": [
            {"claim": "a", "source": "nope"}, {"claim": "b", "source": "comment-100"}]}],
    }
    monkeypatch.setattr(llm_mod, "_chat", fake_chat(answer))

    enhanced = enhance(package, docs, CONFIG)
    ucp.validate(enhanced)
    assert ucp.Package.model_validate(enhanced).verify_references() == []
    assert enhanced["summary"]["sources"] == ["issue"]  # fallback, not the fake key
    assert not any(d["id"].startswith("decision-llm") for d in enhanced["decisions"])
    assert not enhanced.get("conflicts")  # single valid position is not a conflict


def test_filtered_source_is_restored_when_cited(monkeypatch, package_and_docs):
    package, docs = package_and_docs
    # comment-100 may be cited by claims already; pick a key and remove it from
    # the registry to simulate the cited-only filtering.
    package["sources"].pop("comment-100", None)
    package["must_know"] = [c for c in package["must_know"]
                            if "comment-100" not in c["sources"]]
    monkeypatch.setattr(llm_mod, "_chat", fake_chat(LLM_ANSWER))

    enhanced = enhance(package, docs, CONFIG)
    assert "comment-100" in enhanced["sources"]
    assert ucp.Package.model_validate(enhanced).verify_references() == []


def test_bad_json_raises_llm_error(monkeypatch, package_and_docs):
    package, docs = package_and_docs
    monkeypatch.setattr(llm_mod, "_chat", lambda config, prompt: "I refuse.")
    with pytest.raises(LLMError):
        enhance(package, docs, CONFIG)


def test_from_env_reads_openai_api_base(monkeypatch):
    monkeypatch.delenv("UCP_LLM_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_BASE", "https://api.kie.ai/gemini/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("UCP_LLM_MODEL", "gemini-flash")
    cfg = LLMConfig.from_env()
    assert cfg.base_url == "https://api.kie.ai/gemini/v1"
    assert cfg.api_key == "secret"
    assert cfg.model == "gemini-flash"


def test_document_enhance_uses_document_key_not_issue(monkeypatch):
    package = build_document_package(
        copy.deepcopy(CONFLUENCE_PAGE_BUNDLE),
        now=NOW,
    )
    docs = document_llm_docs(CONFLUENCE_PAGE_BUNDLE, package["generated_at"])
    answer = {
        "summary": "Confluence page describes ingestion pipeline.",
        "key_sources": [],
        "decisions": [],
        "conflicts": [],
    }
    monkeypatch.setattr(
        llm_mod,
        "_chat",
        lambda config, prompt: "```json\n" + json.dumps(answer) + "\n```",
    )

    enhanced = enhance(package, docs, CONFIG)
    assert enhanced["summary"]["sources"] == ["document"]
    assert enhanced["summary"]["confidence"] == 0.7
    assert "llm_model" in enhanced["generator"]


def test_cli_degrades_gracefully_when_llm_fails(monkeypatch, capsys, tmp_path):
    import ucp_gen.cli as cli

    monkeypatch.setattr(cli, "fetch_issue_bundle",
                        lambda *a, **k: copy.deepcopy(BUNDLE))
    monkeypatch.setattr(llm_mod, "_chat",
                        lambda config, prompt: (_ for _ in ()).throw(LLMError("boom")))
    out = tmp_path / "task.ucp.json"
    assert cli.main(["github", "acme/rocket#42", "--llm", "-o", str(out)]) == 0
    assert "structure-only" in capsys.readouterr().err
    data = json.loads(out.read_text())
    ucp.validate(data)
    assert "llm_model" not in data["generator"]
