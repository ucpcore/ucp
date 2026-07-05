import ucp
from tests.conftest import requires_spec


@requires_spec
def test_canonical_section_order(example_data):
    text = ucp.render(ucp.Package.model_validate(example_data))
    positions = [
        text.index("# Context: Migrate payment webhooks to v2 API"),
        text.index("## What changed"),
        text.index("## Summary"),
        text.index("## Must know"),
        text.index("## Constraints"),
        text.index("## Risks"),
        text.index("## Decisions"),
        text.index("## Conflicts"),
        text.index("## Recommended actions"),
        text.index("## Timeline"),
        text.index("## Related"),
        text.index("## Sources"),
    ]
    assert positions == sorted(positions), "sections out of canonical order"


@requires_spec
def test_rendering_is_deterministic(example_data):
    pkg = ucp.Package.model_validate(example_data)
    assert ucp.render(pkg) == ucp.render(pkg)


@requires_spec
def test_claims_cite_source_titles(example_data):
    text = ucp.render(ucp.Package.model_validate(example_data))
    assert "[source: Provider changelog: Webhook API v2 migration guide]" in text


@requires_spec
def test_token_budget_shrinks_output_and_protects_core(example_data):
    pkg = ucp.Package.model_validate(example_data)
    full = ucp.render(pkg)
    budget = ucp.estimate_tokens(full) - 100
    trimmed = ucp.render(pkg, token_budget=budget)

    assert ucp.estimate_tokens(trimmed) <= budget
    assert len(trimmed) < len(full)
    # Protected core survives aggressive truncation.
    tiny = ucp.render(pkg, token_budget=1)
    assert "## Summary" in tiny
    assert "## Conflicts" in tiny
    assert "## What changed" in tiny
    assert "## Timeline" not in tiny


@requires_spec
def test_budget_drops_least_salient_first(example_data):
    pkg = ucp.Package.model_validate(example_data)
    full = ucp.render(pkg)
    # Budget forcing exactly some trimming of low-salience material:
    budget = ucp.estimate_tokens(full) - 30
    trimmed = ucp.render(pkg, token_budget=budget)
    # mk-1 (salience 0.97) must outlive lower-salience content.
    assert "HMAC-SHA256" in trimmed
