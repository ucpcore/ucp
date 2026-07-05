# @ucp/core — Universal Context Package reference library (TypeScript)

Reference implementation of the [UCP specification](../../specs/ucp/SPEC.md)
(v0.1.0-draft): schema validation, TypeScript types, and canonical CommonMark
rendering for LLM prompts with token budgeting. Behavior-identical to the
Python `ucp` package (verified by a cross-implementation parity test).

```bash
npm install @ucp/core
```

## Quickstart

```ts
import { loads, render, verifyReferences, type UCPackage } from "@ucp/core";

// Parse + validate (throws UCPValidationError on failure)
const pkg: UCPackage = loads(jsonText);

console.log(pkg.entity.title);

// Canonical prompt rendering (SPEC §7.1)
const prompt = render(pkg);

// Under a token budget: truncates by ascending salience, drops sections in
// SPEC §7.2 order (summary/conflicts/diff survive longest)
const compact = render(pkg, { tokenBudget: 1500 });

// Referential integrity (ucp-core profile)
const dangling = verifyReferences(pkg); // [] when clean
```

Token counting uses a fast `length / 4` heuristic; pass `countTokens` in
`render` options for exact budgets.

## Development

```bash
npm install
npm test           # vitest against the spec examples + conformance suite
npm run sync-schema  # regenerate src/schema.ts from the canonical schema
npm run build
```
