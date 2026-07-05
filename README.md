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
