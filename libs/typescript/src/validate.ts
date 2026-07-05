import { Ajv2020 } from "ajv/dist/2020.js";
import addFormatsImport from "ajv-formats";

import { ucpSchema } from "./schema.js";
import type { UCPackage } from "./types.js";

// CJS/ESM interop under NodeNext: at runtime the default import is the
// plugin function itself, but the CJS type surface says otherwise.
const addFormats = addFormatsImport as unknown as (ajv: Ajv2020) => void;

export class UCPValidationError extends Error {
  constructor(public readonly errors: string[]) {
    super(errors.join("; "));
    this.name = "UCPValidationError";
  }
}

const ajv = new Ajv2020({ strict: true, allErrors: true });
addFormats(ajv);
const validator = ajv.compile(ucpSchema as unknown as object);

/** The bundled UCP JSON Schema (identical to the canonical spec schema). */
export function schema(): Record<string, unknown> {
  return ucpSchema as unknown as Record<string, unknown>;
}

/** Validate and return human-readable error messages (empty array = valid). */
export function iterErrors(data: unknown): string[] {
  if (validator(data)) return [];
  return (validator.errors ?? []).map(
    (e) => `${e.instancePath || "<root>"}: ${e.message ?? "invalid"}`
  );
}

/** Validate, throwing {@link UCPValidationError} when the document does not conform. */
export function validate(data: unknown): asserts data is UCPackage {
  const errors = iterErrors(data);
  if (errors.length > 0) throw new UCPValidationError(errors);
}

/** Parse a UCP document from a JSON string, validating by default. */
export function loads(text: string, options: { validate?: boolean } = {}): UCPackage {
  const data: unknown = JSON.parse(text);
  if (options.validate !== false) validate(data);
  return data as UCPackage;
}

/**
 * Referential integrity check (ucp-core profile): every source key referenced
 * by a claim, decision, conflict, change, or event must exist in the registry.
 * Returns dangling references; an empty array means the package is clean.
 */
export function verifyReferences(pkg: UCPackage): string[] {
  const known = new Set(Object.keys(pkg.sources));
  const dangling: string[] = [];
  const collect = (keys: string[] | undefined, where: string) => {
    for (const key of keys ?? []) {
      if (!known.has(key)) dangling.push(`${where}: ${key}`);
    }
  };

  collect(pkg.summary?.sources, "summary");
  for (const section of ["must_know", "constraints", "risks", "recommended_actions"] as const) {
    for (const claim of pkg[section] ?? []) collect(claim.sources, `${section}[${claim.id}]`);
  }
  for (const decision of pkg.decisions ?? []) {
    collect(decision.sources, `decisions[${decision.id}]`);
  }
  for (const conflict of pkg.conflicts ?? []) {
    conflict.positions.forEach((position, i) =>
      collect(position.sources, `conflicts[${conflict.id}].positions[${i}]`)
    );
  }
  pkg.context_diff?.changes.forEach((change, i) =>
    collect(change.sources, `context_diff.changes[${i}]`)
  );
  (pkg.history ?? []).forEach((event, i) => collect(event.sources, `history[${i}]`));
  return dangling;
}
