import copy
from datetime import datetime, timezone

import ucp

from ucp_gen import build_jira_package

from .fixtures_jira import JIRA_BUNDLE

NOW = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)


def build(**kwargs):
    return build_jira_package(copy.deepcopy(JIRA_BUNDLE), now=NOW, **kwargs)


def test_output_is_schema_valid_and_reference_clean():
    data = build()
    ucp.validate(data)
    pkg = ucp.Package.model_validate(data)
    assert pkg.verify_references() == []


def test_entity_reflects_the_ticket():
    pkg = ucp.Package.model_validate(build())
    assert pkg.entity.ref.system == "jira"
    assert pkg.entity.ref.id == "PAY-482"
    assert pkg.entity.ref.type == "bug"
    assert pkg.entity.status == "Done"
    assert pkg.entity.assignee.display_name == "Bob Dole"
    assert pkg.entity.ref.url == "https://acme.atlassian.net/browse/PAY-482"


def test_status_claim_includes_resolution():
    pkg = ucp.Package.model_validate(build())
    top = max(pkg.must_know, key=lambda c: c.salience or 0)
    assert top.id == "status"
    assert "Done" in top.text and "Fixed" in top.text


def test_summary_skips_wiki_header():
    pkg = ucp.Package.model_validate(build())
    assert pkg.summary.text.startswith("When more than ~50 webhook events")


def test_blocked_by_link_becomes_constraint_and_dependency():
    pkg = ucp.Package.model_validate(build())
    blocked = next(c for c in pkg.must_know if c.id == "link-INFRA-77")
    assert blocked.kind == "constraint"
    assert "is blocked by" in blocked.text
    assert [d.id for d in pkg.dependencies] == ["INFRA-77"]


def test_resolution_becomes_accepted_decision():
    pkg = ucp.Package.model_validate(build())
    accepted = [d for d in pkg.decisions if d.status == "accepted"]
    assert len(accepted) == 1
    assert "Fixed" in accepted[0].decision


def test_decision_marker_comment_becomes_proposed():
    pkg = ucp.Package.model_validate(build())
    proposed = [d for d in pkg.decisions if d.status == "proposed"]
    assert len(proposed) == 1
    assert proposed[0].sources == ["comment-9002"]


def test_changelog_becomes_history_and_rank_noise_is_dropped():
    pkg = ucp.Package.model_validate(build())
    summaries = " | ".join(event.summary for event in pkg.history)
    assert "status: To Do \u2192 In Progress" in summaries
    assert "Rank" not in summaries
    stamps = [event.occurred_at for event in pkg.history]
    assert stamps == sorted(stamps)


def test_related_objects_cover_links_parent_and_subtasks():
    pkg = ucp.Package.model_validate(build())
    relations = {obj.ref.id: obj.relation for obj in pkg.related_objects}
    assert relations["INFRA-77"] == "is blocked by"
    assert relations["PAY-400"] == "child of"
    assert relations["PAY-483"] == "subtask"


def test_since_produces_context_diff():
    data = build(since="2026-06-15T00:00:00Z")
    ucp.validate(data)
    pkg = ucp.Package.model_validate(data)
    assert "ucp-temporal" in pkg.profiles
    assert any("Done" in change.summary for change in pkg.context_diff.changes)


def test_rendering_fits_budget():
    pkg = ucp.Package.model_validate(build())
    tight = pkg.render(token_budget=500)
    assert ucp.estimate_tokens(tight) <= 500
    assert "Payment webhook drops events" in tight
