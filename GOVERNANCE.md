# UCP Governance

## Current phase: incubation (pre-1.0)

The specification is maintained by the Context OS team, which acts as editor.
During incubation:

- Anyone may propose changes (see [CONTRIBUTING.md](./CONTRIBUTING.md)).
- The editors merge changes after public discussion and rough consensus.
- Editors commit to responding to normative-change proposals within 14 days.

## Design principles that govern decisions

1. **Adoption over elegance.** If a change makes UCP harder to produce or
   consume, it needs an extraordinary justification.
2. **Vendor neutrality.** UCP must remain fully usable without any
   Context OS product. Features that only make sense with a specific vendor
   belong in `extensions`, not in the core spec.
3. **Provenance, time, and audience are the core.** Changes that weaken
   mandatory provenance, temporal semantics, or audience binding will be
   rejected.

## Path to neutral governance

When the ecosystem reaches meaningful third-party adoption (multiple
independent producers in production), the specification will be transferred
to a neutral foundation (e.g., Linux Foundation) with a formal technical
steering committee. This commitment is part of the spec's value proposition:
UCP is not a single company's format.

## Versioning authority

Releases are tagged by the editors. Pre-1.0, minor versions may contain
breaking changes (announced in the changelog). From 1.0.0, semver applies
strictly.
