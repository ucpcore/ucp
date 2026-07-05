# ucp — Universal Context Package reference library (Python)

Reference implementation of the [UCP specification](../../specs/ucp/SPEC.md)
(v0.1.0-draft): schema validation, typed Pydantic models, and canonical
CommonMark rendering for LLM prompts with token budgeting.

```bash
pip install pyucp   # distribution "pyucp", import name "ucp"
```

## Quickstart

```python
import ucp

# Load and validate a package (raises ucp.UCPValidationError on failure)
pkg = ucp.load("task.ucp.json")

print(pkg.entity.title)
print(pkg.must_know[0].text)

# Canonical prompt rendering (SPEC §7.1)
prompt = ucp.render(pkg)

# Under a token budget: truncates by ascending salience, drops sections
# in the order defined by SPEC §7.2 (summary/conflicts/diff survive longest)
prompt = ucp.render(pkg, token_budget=1500)

# Validation without parsing into models
errors = ucp.iter_errors({"ucp_version": "0.1.0"})  # -> list of messages

# Referential integrity (ucp-core profile): every claim source key must exist
dangling = pkg.verify_references()  # -> [] when clean
```

## What this library guarantees

- **Schema validation** against the bundled JSON Schema (draft 2020-12),
  identical to `specs/ucp/schema/ucp.schema.json`.
- **Must-ignore semantics**: unknown fields are preserved, never rejected
  (SPEC §6.1) — models use `extra="allow"`.
- **Provenance enforcement**: a claim without sources fails both schema
  validation and model parsing.
- **Deterministic rendering**: the same package always renders to the same
  prompt, so downstream LLM behavior is reproducible.

Token counting uses a fast `len(text) / 4` heuristic; pass your own counter
via `render(pkg, token_budget=..., count_tokens=fn)` for exact budgets.

## Development

```bash
pip install -e ".[dev]"
pytest
```

Tests run against the spec's `examples/` and `conformance/` suites when the
repository layout is available.
