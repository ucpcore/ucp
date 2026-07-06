import copy
from datetime import datetime, timezone

import ucp

from ucp_gen import build_package

from .fixtures import BUNDLE, user

NOW = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)


def build(**kwargs):
    return build_package(copy.deepcopy(BUNDLE), now=NOW, **kwargs)


def test_output_is_schema_valid_and_reference_clean():
    data = build()
    ucp.validate(data)  # raises on violation
    pkg = ucp.Package.model_validate(data)
    assert pkg.verify_references() == []


def test_entity_reflects_the_issue():
    pkg = ucp.Package.model_validate(build())
    assert pkg.entity.ref.id == "acme/rocket#42"
    assert pkg.entity.status == "closed"
    assert pkg.entity.assignee.id == "github:bob"


def test_summary_takes_first_meaningful_paragraph():
    pkg = ucp.Package.model_validate(build())
    assert pkg.summary.text.startswith("When more than ~50 webhook events")
    assert pkg.summary.sources == ["issue"]


def test_state_claim_has_top_salience():
    pkg = ucp.Package.model_validate(build())
    top = max(pkg.must_know, key=lambda c: c.salience or 0)
    assert top.id == "state"
    assert "closed" in top.text and "completed" in top.text


def test_merged_pr_becomes_accepted_decision():
    pkg = ucp.Package.model_validate(build())
    accepted = [d for d in pkg.decisions if d.status == "accepted"]
    assert len(accepted) == 1
    assert "PR #55" in accepted[0].decision
    assert accepted[0].decided_by.id == "github:carol"


def test_decision_marker_in_comment_becomes_proposed_decision():
    bundle = copy.deepcopy(BUNDLE)
    bundle["linked_pulls"] = []  # no merged PR — proposed decision should survive
    pkg = ucp.Package.model_validate(build_package(bundle, now=NOW))
    proposed = [d for d in pkg.decisions if d.status == "proposed"]
    assert len(proposed) == 1
    assert "at-least-once delivery" in proposed[0].decision
    assert proposed[0].sources == ["comment-101"]


def test_merged_pr_supersedes_proposed_comment_decision():
    pkg = ucp.Package.model_validate(build())
    proposed = [d for d in pkg.decisions if d.status == "proposed"]
    assert proposed == []
    accepted = [d for d in pkg.decisions if d.status == "accepted"]
    assert len(accepted) == 1


def test_coverage_not_truncated_on_small_issue():
    data = build()
    ucp.validate(data)
    cov = data["coverage"]
    assert cov["truncated"] is False
    assert cov["sources_included"] == len(data["sources"])
    comments = next(s for s in cov["streams"] if s["kind"] == "comments")
    assert comments["retrieved"] == 2
    assert comments["represented"] == 2
    timeline = next(s for s in cov["streams"] if s["kind"] == "timeline")
    assert timeline["retrieved"] == len(BUNDLE["timeline"])
    assert timeline["represented"] == len(BUNDLE["timeline"])


def test_coverage_not_truncated_when_timeline_has_unmapped_events():
    bundle = copy.deepcopy(BUNDLE)
    bundle["timeline"].append({
        "event": "referenced",
        "created_at": "2026-06-21T00:00:00Z",
        "actor": user("bot"),
    })
    data = build_package(bundle, now=NOW)
    ucp.validate(data)
    assert data["coverage"]["truncated"] is False
    timeline = next(s for s in data["coverage"]["streams"] if s["kind"] == "timeline")
    assert timeline["retrieved"] == 6
    assert timeline["represented"] == 5
    bundle = copy.deepcopy(BUNDLE)
    bundle["issue"]["comments"] = 596
    bundle["fetch_meta"] = {"comments_limit": 200, "timeline_limit": 200}
    data = build_package(bundle, now=NOW)
    ucp.validate(data)
    cov = data["coverage"]
    assert cov["truncated"] is True
    assert cov["sources_considered"] >= 596
    comments = next(s for s in cov["streams"] if s["kind"] == "comments")
    assert comments["available"] == 596
    assert comments["retrieved"] == 2
    assert comments["fetch_limit"] == 200


def test_every_source_carries_content_hash():
    data = build()
    assert len(data["sources"]) == 4  # issue + 2 comments + 1 PR
    for source in data["sources"].values():
        assert source["content_hash"].startswith("sha256:")


def test_history_is_chronological():
    pkg = ucp.Package.model_validate(build())
    stamps = [event.occurred_at for event in pkg.history]
    assert stamps == sorted(stamps)
    assert "Issue opened by alice" in pkg.history[0].summary


def test_since_produces_context_diff_and_temporal_profile():
    data = build(since="2026-06-15T00:00:00Z")
    ucp.validate(data)
    pkg = ucp.Package.model_validate(data)
    assert "ucp-temporal" in pkg.profiles
    summaries = [change.summary for change in pkg.context_diff.changes]
    assert summaries == ["bob closed the issue"]  # the only event after `since`


def test_no_since_means_no_diff():
    data = build()
    assert "context_diff" not in data
    assert data["profiles"] == ["ucp-core"]


def test_summary_skips_template_headers_and_code_fences():
    bundle = copy.deepcopy(BUNDLE)
    bundle["issue"]["body"] = (
        "## Description\n\n```\nTraceback: boom\n```\n\n"
        "The actual explanation of the problem.\n\nMore details."
    )
    pkg = ucp.Package.model_validate(build_package(bundle, now=NOW))
    assert pkg.summary.text == "The actual explanation of the problem."


def test_unreferenced_comment_sources_are_pruned():
    bundle = copy.deepcopy(BUNDLE)
    # 30 extra comments with empty bodies: they produce no claims, so their
    # sources must not survive into the registry.
    for i in range(30):
        bundle["comments"].append({
            "id": 1000 + i, "user": {"login": f"user{i}"},
            "created_at": f"2026-06-0{1 + i % 9}T00:00:00Z",
            "html_url": f"https://github.com/acme/rocket/issues/42#issuecomment-{1000 + i}",
            "body": "",
        })
    data = build_package(bundle, now=NOW)
    ucp.validate(data)
    assert len(data["sources"]) == 4  # unchanged: issue + 2 real comments + PR
    assert ucp.Package.model_validate(data).verify_references() == []


def test_excerpt_cuts_on_word_boundary():
    bundle = copy.deepcopy(BUNDLE)
    bundle["comments"][0]["body"] = "word " * 100  # far beyond the excerpt limit
    data = build_package(bundle, now=NOW)
    excerpt = data["sources"]["comment-100"]["excerpt"]
    assert excerpt.endswith("word…")


def test_rendering_fits_budget_and_keeps_core():
    pkg = ucp.Package.model_validate(build())
    tight = pkg.render(token_budget=500)
    assert ucp.estimate_tokens(tight) <= 500
    assert "Payment webhook drops events" in tight
