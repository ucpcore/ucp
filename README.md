# Universal Context Package (UCP)

**An open specification for packaging work context for Large Language Models.**

Version: `0.1.0-draft` · License: Apache 2.0 · Status: Draft

---

## The problem

LLMs don't know your work context. Before an AI can help with a task, someone —
a human or a pipeline — must gather the relevant documents, decisions,
constraints, and risks scattered across Jira, Confluence, GitHub, Drive, CRMs
and ERPs, and paste them into a prompt.

Existing standards solve adjacent problems:

- **MCP** (Model Context Protocol) standardizes *access* to data sources.
- **RAG** pipelines retrieve *similar* chunks.
- **UCP** standardizes *understanding*: a verifiable, permission-aware,
  time-aware package of what a person (or agent) needs to know **right now**
  to act on a specific task.

> MCP is the pipe. UCP is what flows through it.

## What a UCP looks like

```json
{
  "ucp_version": "0.1.0",
  "id": "urn:uuid:7f9c2e14-...",
  "generated_at": "2026-07-05T13:40:00Z",
  "generator": { "name": "context-os", "version": "0.2.0" },
  "profiles": ["ucp-core", "ucp-temporal", "ucp-secure"],
  "entity": {
    "ref": { "system": "jira", "type": "issue", "id": "PAY-482",
             "url": "https://acme.atlassian.net/browse/PAY-482" },
    "title": "Migrate payment webhooks to v2 API"
  },
  "summary": { "text": "…", "sources": ["src-1", "src-2"] },
  "must_know": [
    {
      "id": "mk-1",
      "text": "Webhook signatures must use HMAC-SHA256; v1 keys are revoked on Aug 1.",
      "salience": 0.97,
      "confidence": 0.9,
      "sources": ["src-3"],
      "valid_from": "2026-06-12T00:00:00Z"
    }
  ],
  "decisions": [
    {
      "id": "dec-1",
      "decision": "Keep idempotency keys in Redis, not Postgres",
      "status": "accepted",
      "decided_at": "2026-05-20T09:00:00Z",
      "sources": ["src-4"]
    }
  ],
  "conflicts": [],
  "context_diff": { "since": "2026-07-01T08:00:00Z", "changes": [] },
  "sources": {
    "src-1": { "system": "jira", "type": "issue", "title": "PAY-482",
               "url": "…", "content_hash": "sha256:…" }
  }
}
```

## Design principles

1. **Provenance is mandatory.** Every claim links to its sources. A claim
   without sources is invalid in every profile.
2. **Time is first-class.** Claims carry validity windows; stale facts are
   distinguishable from current ones. Contradictions are representable, not
   silently merged.
3. **Permission-aware.** A package declares its audience and whether access
   control was enforced during assembly. Packages are *per-audience* by design.
4. **LLM-agnostic.** A canonical rendering algorithm turns any UCP into a
   deterministic prompt for any model. Salience scores define truncation order
   under a token budget.
5. **Forward-compatible.** Consumers must ignore unknown fields. Extensions use
   namespaced keys. The schema evolves under semver.

## What UCP gives you

**Structure.** Every consumer — an LLM, an agent, any application — receives the
same predictable sections: what is going on (`summary`), what you must know
(`must_know`), why things were decided (`decisions`), what contradicts what
(`conflicts`), what changed since your last visit (`context_diff`). The model
doesn't dig meaning out of a document dump; the meaning is already laid out.

**Token economy.** A raw retrieval dump for a task easily costs 50–100K
tokens; a UCP package carries the same actionable knowledge in 1–2K. Inside
the package, per-claim `salience` defines a deterministic truncation order, so
under any token budget the noise is dropped first and the core (summary,
conflicts, diff) survives.

**Verifiability.** A claim without sources is schema-invalid. Sources carry
content hashes. An AI summary you can audit is an AI summary you can trust.

**Access safety.** A package declares who it was assembled for and attests
that every source passed an access-control check.

## Generate a real package in 30 seconds

The reference toolchain turns any public GitHub issue or Jira ticket into
a UCP — by default no LLM involved, structure only:

```bash
pip install ucp-gen

# JSON package: claims, decisions, timeline, hashed sources
ucp-gen github pallets/flask#5961 -o task.ucp.json
ucp-gen jira PROJ-123 -o task.ucp.json   # needs JIRA_BASE_URL + token

# or the canonical LLM rendering, capped at 1500 tokens
ucp-gen github pallets/flask#5961 --markdown --token-budget 1500

# optional: add semantic understanding via any OpenAI-compatible endpoint
ucp-gen github pallets/flask#5961 --llm -o task.ucp.json
```

Serve the result to Cursor / Claude Code via the reference MCP server:

```bash
pip install ucp-mcp
ucp-mcp --dir .   # exposes list_contexts / get_context / get_context_markdown
```

Or run everything as one self-hosted server (REST + MCP over Streamable HTTP):

```bash
docker run --rm -p 8080:8080 ghcr.io/ucpcore/ucp-server:latest
# or without Docker: uvx --from ucpcore-server ucp-server
```

Point Cursor / Claude Code at `http://localhost:8080/mcp`, or use the REST API
(`POST /v1/generate`); see [`libs/server`](./libs/server/) for details.

## Measured on real issues

Same token estimator on both sides (~4 chars/token); "raw thread" is the
text you would otherwise paste into the model — title, body, comments,
linked-PR bodies. Reproduce with
[`tools/benchmark_context.py`](./tools/benchmark_context.py):

| Issue | Comments | Raw thread | UCP |
|---|---|---|---|
| `microsoft/vscode#519` | first 200 of 596 | ~18,500 | **~1,200** |
| `rust-lang/rust#158622` | 12 | ~4,450 | **~1,450** |
| `pallets/flask#5961` | 4 | ~800 | **~700** |
| `pallets/flask#5948` | 0 | ~500 | **~330** |

The win grows with thread size — a decade-long discussion collapses ~15×
while keeping decisions, conflicts and provenance. On small issues the
token count is similar, but the package is still structured, hashed and
audience-aware instead of being a wall of text. Generated with `ucp-gen`
0.1.1, 2026-07-05.

## What `--llm` adds

The default pipeline is purely structural: fast, deterministic, no model
involved. The optional `--llm` flag adds a semantic layer through a single
call to any OpenAI-compatible endpoint — `summary` becomes a synthesis of
the whole thread instead of its opening paragraph, comments the model flags
as pivotal get a salience boost, and decisions and conflicts that exist
only in prose are extracted into their structured fields.

Measured on `microsoft/vscode#519` — 596 comments over a decade, of which
200 fit the package (17 sources, ~1,623 rendered tokens) — the enriched
package captures what no structural field of GitHub carries. The summary
explains *why* the feature was never built: the VS Code team declined
because list and tree heights are hard-coded, the community relies on
workarounds (zoom, custom CSS), and a community PR was not accepted. A
`conflict` records the dispute over whether Electron or VS Code's
hard-coded styles are to blame, both positions citing specific hashed
comments. A `decision` with status `rejected` records that the request is
not on the roadmap — information stated only in prose, invisible to the
structural mode.

The guarantees do not change. The package still validates against the
schema; every LLM-added claim must cite source ids that exist in the
package (hallucinated citations are dropped); `generator.llm_model` records
which model produced the enrichment; and if the endpoint is unreachable the
generator degrades gracefully to the structural package with a warning.

## Industry-neutral by design

The structure of "understanding a task" is the same everywhere; only the
content differs. A lawyer opening a case, a plant engineer opening a work
order, and a bank analyst opening an application all need the same sections —
facts, constraints, decisions, conflicts, changes. UCP keeps vocabularies
open (`system: 1c`, `scada`, `ehr`, …), puts system-specific fields in
`attributes`/`extensions`, and keeps the mandatory core (provenance, time,
audience) domain-free.

The honest boundary: **the format is universal; the builder is not.** UCP
defines what the artifact of understanding looks like. Assembling it well from
a particular industry's systems — connectors, domain entity extraction,
ranking — is where producers (like Context OS) compete. That is deliberate:
the standard is open, the craft is the market.

## Repository layout

| Path | Contents |
|---|---|
| [`SPEC.md`](./SPEC.md) | The normative specification |
| [`schema/ucp.schema.json`](./schema/ucp.schema.json) | JSON Schema (draft 2020-12) |
| [`examples/`](./examples/) | Complete example packages |
| [`conformance/`](./conformance/) | Conformance test suite (valid / invalid packages) |
| `libs/python` | `pyucp` — models, validation, canonical rendering |
| `libs/typescript` | `@ucpcore/core` — types, validation, canonical rendering |
| `libs/mcp-server` | `ucp-mcp` — serve packages over MCP |
| `libs/gen` | `ucp-gen` — generate packages from GitHub issues |
| `libs/server` | `ucpcore-server` — self-hosted generation service (REST + MCP) |

## Conformance profiles

| Profile | Guarantees |
|---|---|
| `ucp-core` | Valid structure, entity, summary, sources, provenance on every claim |
| `ucp-temporal` | Validity windows, `context_diff`, `conflicts` populated when detected |
| `ucp-secure` | Audience declared, access control attested, audit reference present |

A minimal producer can ship `ucp-core` only. See [SPEC.md §5](./SPEC.md).

## Status of this document

This is a **draft** published for community review. Breaking changes are
expected before 1.0.0. Feedback via issues and pull requests is welcome.
