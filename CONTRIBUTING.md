# Contributing to UCP

UCP is an open specification. Changes happen in the open, through issues and
pull requests. All contributions are licensed under Apache 2.0.

## How changes are made

1. **Small fixes** (typos, clarifications that don't change meaning) — open a
   PR directly.
2. **Normative changes** (anything that changes what producers or consumers
   MUST/SHOULD do) — open a GitHub Discussion or issue first, describing:
   - the problem the change solves (real use case, not hypothetical);
   - the proposed change;
   - impact on existing producers/consumers (breaking or additive).
   After rough consensus, submit a PR updating `SPEC.md`, the JSON Schema,
   and conformance tests together.

## Rules for spec changes

- Every normative change MUST update `SPEC.md`, `schema/ucp.schema.json`,
  and add at least one conformance test case.
- Additive changes (new optional fields) are minor version bumps.
  Breaking changes require a major version bump and strong justification.
- Unknown-field tolerance (must-ignore) is non-negotiable: no change may
  require consumers to reject unknown fields.
- Vocabularies (`system`, `type`, `kind`, `relation`) stay open. We add
  RECOMMENDED values; we do not close the lists.

## Validating locally

```bash
npm install
npm test        # validates schema, examples, and conformance suite
```

## Conformance test suite

- `conformance/valid/` — documents that MUST validate.
- `conformance/invalid/` — documents that MUST be rejected.

If you find a document that validates but shouldn't (or vice versa), that's
a bug in the schema — please file it with the document attached.

## Code of conduct

Be professional and assume good faith. Technical disagreements are resolved
with use cases and data, not volume.
