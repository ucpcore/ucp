# ucp-gen

Generate [Universal Context Packages](https://github.com/ucpcore/ucp) from
real systems — no LLM in the loop. The first supported source is GitHub
issues: one command turns an issue, its comments, timeline and linked pull
requests into a validated, provenance-backed `.ucp.json`.

```bash
pip install ucp-gen
export GITHUB_TOKEN=...   # optional, raises the API rate limit

# JSON package to a file
ucp-gen github vercel/next.js#12345 -o task.ucp.json

# canonical LLM rendering, capped at 1500 tokens
ucp-gen github owner/repo#42 --markdown --token-budget 1500

# include a "what changed since" diff (adds the ucp-temporal profile)
ucp-gen github owner/repo#42 --since 2026-06-01T00:00:00Z
```

## What the mapping does

| GitHub | UCP |
|---|---|
| issue title / state / assignee | `entity` |
| first meaningful paragraph of the body | `summary` |
| state, assignees, milestone, labels, PR states, comment gists | `must_know` claims with salience |
| merged linked PRs | `decisions` (accepted) |
| comments with decision markers ("we decided", "let's go with") | `decisions` (proposed) |
| issue timeline | `history`, and `context_diff` when `--since` is given |
| linked PRs | `related_objects` |
| every issue / comment / PR | `sources` entry with URL + content hash |

Every claim cites its sources; every source carries a `sha256` content hash.
The output always validates against the UCP schema before it is written —
the generator will fail rather than emit an invalid package.

Feed the result to any UCP consumer, e.g. the reference MCP server:

```bash
pip install ucp-mcp
ucp-gen github owner/repo#42 -o ./contexts/task.ucp.json
ucp-mcp --dir ./contexts   # Cursor / Claude Code now sees the context
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

Part of the UCP reference toolchain (Apache 2.0).
