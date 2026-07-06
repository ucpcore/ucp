# ucp-gen

Generate [Universal Context Packages](https://github.com/ucpcore/ucp) from
real systems. Two sources are supported — GitHub issues and Jira tickets —
and one command turns an issue with its comments, history and links into a
validated, provenance-backed `.ucp.json`. By default no LLM is involved:
the structure alone already carries the facts, decisions and timeline.

```bash
pip install ucp-gen

# GitHub (GITHUB_TOKEN optional, raises the API rate limit)
ucp-gen github vercel/next.js#12345 -o task.ucp.json

# Jira (Cloud: email + API token; Server/DC: personal access token)
export JIRA_BASE_URL=https://yourco.atlassian.net
export JIRA_EMAIL=you@yourco.com
export JIRA_API_TOKEN=...
ucp-gen jira PROJ-123 -o task.ucp.json

# canonical LLM rendering, capped at 1500 tokens
ucp-gen github owner/repo#42 --markdown --token-budget 1500

# include a "what changed since" diff (adds the ucp-temporal profile)
ucp-gen github owner/repo#42 --since 2026-06-01T00:00:00Z

# pretty-print any package in the terminal
ucp-gen view task.ucp.json
```

The CLI is built for humans: spinners while fetching, checkmarks per step,
a summary tree after writing, rich `--help` with grouped options, and an
interactive prompt when you omit the issue reference. Decorations go to
stderr — stdout stays pure JSON/Markdown, so piping is always safe:

```
✓ pallets/flask#5961 — issue + 4 comments + 1 linked PRs
✓ valid ucp-core package — 6 sources, sha256-hashed
📦 wrote task.ucp.json
├── Flask 3.1.3 test breaks after Werkzeug update…
├── claims      7 must-know
├── decisions   1 (1 accepted)
├── sources     6
└── tokens      ~713 rendered
```

## Coverage and decision dedup (0.3.1+)

Every package includes a `coverage` block: whether material was truncated,
how many upstream artifacts were considered vs included, and per-stream counts
(comments retrieved vs represented, timeline fetch limits). On mega-threads
like `microsoft/vscode#519` you get `truncated: true` with `available: 596`
even when only 200 comments were fetched.

When a merged linked PR exists, **proposed** decisions extracted from comment
phrases like "we decided …" are dropped — the merged PR is the authoritative
accepted signal (SPEC §4.11).

## Optional LLM enhancement (`--llm`)

Structure tells you *what happened*; it cannot tell you which of 200
comments contains the key insight. `--llm` adds that layer with a single
call to any OpenAI-compatible endpoint (OpenAI, kie.ai, OpenRouter, a
LiteLLM proxy, local Ollama):

```bash
export UCP_LLM_BASE_URL=https://your-provider.example/v1   # any OpenAI-compatible URL
export UCP_LLM_API_KEY=...
export UCP_LLM_MODEL=your-model

ucp-gen github owner/repo#42 --llm -o task.ucp.json
```

What it changes: `summary` becomes a real synthesis of the whole thread
(marked with `confidence`), comments the model flags as important get a
salience boost, and decisions/conflicts stated in prose are extracted.
Provenance survives: the model may only cite the source keys it was given —
hallucinated citations are dropped, and every added claim still points at a
real, hashed source. The model used is recorded in `generator.llm_model`.
If the call fails, you get the structure-only package and a warning, never
a broken one.

A real run on `microsoft/vscode#519` (596 comments over ten years; 200 in
the package, 17 sources, ~1,623 rendered tokens) shows the difference: the
enriched summary explains why the feature was never built, a `conflict`
captures the "Electron is at fault" vs "VS Code's hard-coded styles are at
fault" dispute with both positions citing hashed comments, and a `decision`
with status `rejected` records that the request is off the roadmap — none
of which exists in any structured GitHub field.

## What the mapping does

| GitHub | Jira | UCP |
|---|---|---|
| title / state / assignee | summary / status / assignee | `entity` |
| first meaningful paragraph | first meaningful paragraph | `summary` |
| state, milestone, labels, PR states, comment gists | status+resolution, priority, due date, fix versions, links, comment gists | `must_know` claims with salience |
| merged linked PRs | resolution | `decisions` (accepted; supersedes proposed comment decisions) |
| "we decided" comments | "we decided" comments | `decisions` (proposed, unless merged PR exists) |
| issue timeline | changelog | `history`, and `context_diff` with `--since` |
| fetch limits / comment counts | — | `coverage` (truncated honesty) |
| — | "is blocked by" links | `dependencies` |
| linked PRs | links, parent, subtasks | `related_objects` |
| every cited issue / comment / PR | every cited ticket / comment | `sources` with URL + content hash |

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
