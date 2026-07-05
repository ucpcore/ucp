# Universal Context Package Specification

- Version: **0.1.0-draft**
- Date: 2026-07-05
- License: Apache 2.0
- Schema: [`schema/ucp.schema.json`](./schema/ucp.schema.json)

## Abstract

The Universal Context Package (UCP) is an open, JSON-based format for
packaging the working context of a task so that any Large Language Model —
or any human — can understand the task without reading the underlying corpus.
A UCP is a *claim-based* document: every statement it contains is attributable
to sources, positioned in time, and scored for relevance. UCP is transport-
agnostic and model-agnostic. It complements, and does not replace, data-access
protocols such as MCP.

## 1. Introduction

### 1.1. Problem

Knowledge workers assemble context manually: reading tickets, wikis, code
review threads, and chat logs, then summarizing them for an AI assistant.
Retrieval systems return *similar text*; they do not answer the questions that
determine whether work can proceed safely:

- What is true **now** (as opposed to what was true when a document was written)?
- What **changed** since I last looked?
- **Why** were key decisions made?
- Which statements **contradict** each other?
- Am I even **allowed** to see this?

### 1.2. Scope

UCP defines:

1. a data model for task context (§4);
2. conformance profiles for producers (§5);
3. extensibility and versioning rules (§6);
4. a canonical rendering algorithm for LLM prompts (§7);
5. security and privacy requirements (§8).

UCP does **not** define: how context is collected, ranked, or stored; wire
protocols; authentication. Those are producer concerns.

### 1.3. Terminology

- **Package** — a single UCP document.
- **Producer** — software that assembles and emits packages.
- **Consumer** — software (LLM adapter, sidebar UI, agent) that reads packages.
- **Claim** — an atomic statement with provenance (§4.4).
- **Source** — an addressable origin document or record (§4.5).
- **Audience** — the principal (user or agent) a package was assembled for.

## 2. Conventions

The key words MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY are to be
interpreted as described in RFC 2119. JSON field names are `snake_case`.
All timestamps MUST be RFC 3339 / ISO 8601 strings in UTC.

## 3. Core concepts

### 3.1. Everything is a claim

UCP sections (`must_know`, `constraints`, `risks`, `recommended_actions`) share
one structure: the **Claim** (§4.4). This uniformity is deliberate: it makes
provenance, temporal validity, and salience universal rather than per-section
afterthoughts, and it lets consumers process all sections with one code path.

### 3.2. Sources registry

Claims reference sources by key into a single `sources` map. This normalizes
provenance (one source, many claims), enables integrity checking via content
hashes, and keeps packages compact.

### 3.3. Bi-temporality

A claim distinguishes *when it was asserted* (`asserted_at`) from *when it is
valid* (`valid_from` / `valid_to`). A claim whose validity has ended is
**stale**; producers SHOULD exclude stale claims from `must_know` and MAY
surface them in `conflicts` or `history` instead.

### 3.4. Audience binding

A package is assembled **for a specific principal**. Access-control decisions
are made at assembly time; therefore a package MUST NOT be re-served to a
different principal (§8).

## 4. Data model

### 4.1. Top-level object

| Field | Type | Req | Description |
|---|---|---|---|
| `ucp_version` | string | MUST | Spec version this package conforms to (semver). |
| `id` | string (URI) | MUST | Globally unique package id. `urn:uuid:` RECOMMENDED. |
| `generated_at` | timestamp | MUST | Assembly time. |
| `generator` | Generator | MUST | Producer name/version. |
| `profiles` | string[] | SHOULD | Conformance profiles claimed (§5). |
| `language` | string (BCP 47) | SHOULD | Primary language of textual content. |
| `audience` | Audience | cond. | Required by `ucp-secure` (§4.9). |
| `entity` | Entity | MUST | The object this package is about (§4.2). |
| `situation` | string | MAY | One line: why this package was built ("user opened issue"). |
| `summary` | Summary | core | What is going on + what needs to be done (§4.3). |
| `must_know` | Claim[] | MAY | Facts required to act correctly. |
| `constraints` | Claim[] | MAY | Hard boundaries (technical, legal, process). |
| `risks` | Claim[] | MAY | What can go wrong. |
| `decisions` | Decision[] | MAY | Accepted decisions with rationale (§4.6). |
| `conflicts` | Conflict[] | MAY | Detected contradictions (§4.7). |
| `context_diff` | ContextDiff | MAY | Changes since a baseline (§4.8). |
| `history` | Event[] | MAY | Timeline of notable events. |
| `dependencies` | EntityRef[] | MAY | Objects this entity depends on / blocks. |
| `related_objects` | RelatedObject[] | MAY | Ranked related documents/objects. |
| `recommended_actions` | Claim[] | MAY | Suggested next steps. |
| `sources` | map<string, Source> | MUST | Provenance registry (§4.5). |
| `budget` | Budget | MAY | Token-budget hints (§7.2). |
| `extensions` | map<string, any> | MAY | Namespaced extensions (§6.2). |

Consumers MUST ignore unknown top-level fields (§6.1).

### 4.2. Entity and EntityRef

`EntityRef` addresses an object in an external system:

```json
{ "system": "jira", "type": "issue", "id": "PAY-482",
  "url": "https://acme.atlassian.net/browse/PAY-482" }
```

- `system` — lowercase identifier of the source system. Open vocabulary;
  RECOMMENDED values: `jira`, `confluence`, `github`, `gitlab`, `gdrive`,
  `slack`, `email`, `bitrix24`, `1c`, `filesystem`, `custom`.
- `type` — object type within the system (open vocabulary): `issue`, `page`,
  `pull_request`, `file`, `message`, `record`.
- `id` — stable identifier within the system. MUST.
- `url` — resolvable link. SHOULD.

`Entity` extends `EntityRef` usage:

| Field | Type | Req |
|---|---|---|
| `ref` | EntityRef | MUST |
| `title` | string | MUST |
| `status` | string | MAY |
| `assignee` | Actor | MAY |
| `attributes` | object | MAY — system-specific fields, non-normative |

### 4.3. Summary

```json
{ "text": "…", "sources": ["src-1", "src-2"], "confidence": 0.9 }
```

`text` MUST be plain text or CommonMark. `sources` SHOULD list the dominant
sources the summary was synthesized from.

### 4.4. Claim

The universal atom of UCP.

| Field | Type | Req | Description |
|---|---|---|---|
| `id` | string | MUST | Unique within the package. |
| `text` | string | MUST | The statement, plain text or CommonMark. |
| `kind` | string | MAY | Open vocabulary: `fact`, `instruction`, `warning`, `assumption`. |
| `salience` | number 0..1 | SHOULD | Importance for THIS task. Drives truncation order (§7.2). |
| `confidence` | number 0..1 | MAY | Producer's confidence the claim is correct. |
| `sources` | string[] | MUST | ≥ 1 key into the `sources` map. **A claim without provenance is invalid.** |
| `asserted_at` | timestamp | MAY | When the underlying statement was made. |
| `valid_from` | timestamp | MAY | Start of validity window. |
| `valid_to` | timestamp \| null | MAY | End of validity; `null`/absent = currently valid. |
| `tags` | string[] | MAY | Free-form labels. |

### 4.5. Source

| Field | Type | Req | Description |
|---|---|---|---|
| `system` | string | MUST | As in EntityRef. |
| `type` | string | MUST | As in EntityRef. |
| `title` | string | MUST | Human-readable name. |
| `url` | string | SHOULD | Deep link to the origin. |
| `author` | Actor | MAY | |
| `created_at` / `updated_at` | timestamp | MAY | |
| `content_hash` | string | SHOULD | `sha256:<hex>` of the content as retrieved. Enables integrity verification. |
| `retrieved_at` | timestamp | SHOULD | When the producer read the source. |
| `trust` | number 0..1 | MAY | Producer-assigned source authority. |
| `excerpt` | string | MAY | Short quoted passage backing the claims. |

Map keys (`src-1`, …) are package-local and carry no meaning.

`Actor`: `{ "id": "…", "display_name": "…", "role": "…" }` — `id` SHOULD be
stable within the source system; `role` is free-form ("tech lead").

### 4.6. Decision

Answers "why is it this way".

| Field | Type | Req |
|---|---|---|
| `id` | string | MUST |
| `decision` | string | MUST — what was decided |
| `rationale` | string | SHOULD — why |
| `status` | enum | MUST — `proposed` \| `accepted` \| `superseded` \| `rejected` |
| `decided_by` | Actor | MAY |
| `decided_at` | timestamp | SHOULD |
| `supersedes` | string | MAY — id of an earlier decision |
| `sources` | string[] | MUST (≥ 1) |

### 4.7. Conflict

A detected contradiction between sources. Producers MUST NOT silently drop
either side of a known contradiction; representing it is the point.

| Field | Type | Req |
|---|---|---|
| `id` | string | MUST |
| `description` | string | MUST — what contradicts what |
| `positions` | Position[] | MUST (≥ 2) |
| `resolution_hint` | string | MAY — e.g. "src-2 is newer and authored by the project lead" |
| `severity` | enum | MAY — `low` \| `medium` \| `high` |

`Position`: `{ "claim": string, "sources": string[], "asserted_at": timestamp? }`

### 4.8. ContextDiff

Changes since a baseline — typically the audience's previous visit.

```json
{
  "since": "2026-07-01T08:00:00Z",
  "baseline": "last_view",
  "changes": [
    { "type": "updated", "target": "document", "summary": "Spec section on API changed",
      "occurred_at": "2026-07-03T10:12:00Z", "sources": ["src-2"] }
  ]
}
```

- `baseline` — open vocabulary: `last_view`, `last_package`, `explicit`.
- `changes[].type` — `added` | `updated` | `removed` | `status_changed`.
- `changes[].target` — open vocabulary: `document`, `comment`, `field`,
  `decision`, `risk`, `dependency`.

An empty `changes` array is meaningful: "nothing changed" is information.

### 4.9. Audience (required by `ucp-secure`)

```json
{
  "principal": { "id": "user:alice@acme.com", "display_name": "Alice" },
  "access_control": {
    "enforced": true,
    "mechanism": "rebac",
    "checked_at": "2026-07-05T13:40:00Z",
    "audit_ref": "audit:9f31…"
  }
}
```

- `access_control.enforced: true` attests that every source in the package was
  verified readable by the principal at `checked_at`.
- `audit_ref` — opaque reference into the producer's audit log.

### 4.10. RelatedObject and Event

`RelatedObject`: `{ "ref": EntityRef, "title": string, "relation": string,
"salience": number?, "reason": string? }` — `relation` is an open vocabulary:
`blocks`, `blocked_by`, `supersedes`, `implements`, `mentions`, `similar`.
`reason` is a human-readable one-liner: *why this object is in the package*
("directly linked from the issue; edited 2 days ago by the assignee").

`Event`: `{ "occurred_at": timestamp, "summary": string, "actor": Actor?,
"sources": string[]? }`

## 5. Conformance profiles

Producers declare profiles in `profiles`. Each profile adds requirements:

### 5.1. `ucp-core`

- Package validates against the JSON Schema.
- `entity`, `summary`, `sources` present and non-empty.
- Every Claim/Decision references ≥ 1 existing source key.
- Every source has `system`, `type`, `title`.

### 5.2. `ucp-temporal` (includes `ucp-core`)

- Claims in `must_know`, `constraints`, `risks` carry `valid_from` or
  `asserted_at` where determinable.
- Stale claims (validity ended) are excluded from `must_know`.
- Detected contradictions are represented in `conflicts`.
- `context_diff` is present when a baseline for the audience is known.

### 5.3. `ucp-secure` (includes `ucp-core`)

- `audience` present with `access_control.enforced: true`.
- Every source was permission-checked for the principal at assembly time.
- The package MUST NOT be served to any other principal.
- `audit_ref` present.

## 6. Extensibility and versioning

### 6.1. Must-ignore

Consumers MUST ignore unknown fields at every level. This is the primary
forward-compatibility mechanism.

### 6.2. Extensions

Producer-specific data goes under `extensions`, keyed by reverse-DNS
namespace:

```json
"extensions": { "ai.contextos.ranking": { "engine": "heuristic-v1" } }
```

Extension keys MUST NOT change the meaning of standard fields.

### 6.3. Versioning

`ucp_version` follows semver. Within a major version, additions are backwards
compatible (must-ignore). Removals or semantic changes require a major bump.
Pre-1.0, minor versions MAY break compatibility (standard semver caveat).

## 7. Rendering for LLMs

### 7.1. Canonical rendering

To make consumer behavior reproducible across models, UCP defines a canonical
CommonMark rendering. Consumers MAY render differently, but SHOULD offer the
canonical form. Order:

1. `# Context: {entity.title}` + entity ref line
2. `## What changed` (`context_diff`, if present and non-empty)
3. `## Summary`
4. `## Must know` — claims as list items, each suffixed with `[source: title]`
5. `## Constraints`, `## Risks`
6. `## Decisions` — `{decision} — {rationale} ({status}, {decided_at})`
7. `## Conflicts` — description + positions with dates; NEVER omitted if present
8. `## Recommended actions`
9. `## Timeline` (`history`, chronological)
10. `## Related` — title, relation, reason
11. `## Sources` — numbered list with URLs

Sections absent from the package are skipped. Within a section, items are
ordered by descending `salience` (unspecified salience sorts last, original
order preserved).

### 7.2. Token budgeting

When a consumer has a token budget, it MUST truncate in ascending-salience
order *within* sections, and drop whole sections in this order:
`history` → `related_objects` → `recommended_actions` → `risks` →
`constraints` → `decisions` → `must_know`. `summary`, `conflicts`, and
`context_diff` are dropped last. Producers MAY supply
`budget: { "token_estimate": n }` per package and `token_estimate` per claim
via extensions.

## 8. Security and privacy considerations

1. **A package is a capability.** It contains synthesized restricted content.
   Treat packages with the same sensitivity as the most sensitive source
   inside them.
2. **No cross-audience reuse.** Caching MUST be per-principal, or the cache
   layer MUST re-verify permissions at serve time (in which case
   `access_control.checked_at` MUST be updated).
3. **Provenance is a leak vector.** Source titles/URLs themselves may be
   confidential. Permission checks apply to the source *entries*, not only to
   claim texts.
4. **Integrity.** Consumers MAY verify `content_hash` against the origin to
   detect tampering or drift.
5. **Prompt injection.** Claim texts originate from untrusted documents.
   Consumers SHOULD delimit rendered context from instructions and MUST NOT
   treat package content as system-level instructions.

## 9. Media type and file extension

- Media type: `application/ucp+json` (registration TBD; use
  `application/json` until then).
- File extension: `.ucp.json`.

## Appendix A. Complete example

See [`examples/jira-task.ucp.json`](./examples/jira-task.ucp.json).

## Appendix B. Relationship to MCP

MCP standardizes how tools and agents *access* systems (transport, auth,
tool-calling). UCP standardizes the *artifact of understanding* assembled from
those systems. A natural composition: an MCP server exposes a
`get_context(entity_ref)` tool that returns a UCP document.

## Changelog

- **0.1.0-draft** (2026-07-05) — initial public draft.
