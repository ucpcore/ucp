import type { UCPackage } from "./types.js";

function collectDanglingRefs(doc: UCPackage): string[] {
  const known = new Set(Object.keys(doc.sources ?? {}));
  const dangling: string[] = [];
  const collect = (keys: string[] | undefined, where: string) => {
    for (const key of keys ?? []) {
      if (!known.has(key)) dangling.push(`${where}: ${key}`);
    }
  };

  collect(doc.summary?.sources, "summary");
  for (const section of ["must_know", "constraints", "risks", "recommended_actions"] as const) {
    for (const claim of doc[section] ?? []) {
      collect(claim.sources, `${section}[${claim.id}]`);
    }
  }
  for (const decision of doc.decisions ?? []) {
    collect(decision.sources, `decisions[${decision.id}]`);
  }
  for (const conflict of doc.conflicts ?? []) {
    conflict.positions.forEach((position, i) => {
      collect(position.sources, `conflicts[${conflict.id}].positions[${i}]`);
    });
  }
  doc.context_diff?.changes.forEach((change, i) => {
    collect(change.sources, `context_diff.changes[${i}]`);
  });
  (doc.history ?? []).forEach((event, i) => collect(event.sources, `history[${i}]`));
  return dangling;
}

/** Profile rules from SPEC §5 (beyond JSON Schema). */
export function iterProfileErrors(doc: UCPackage): string[] {
  const profiles = doc.profiles ?? [];
  if (profiles.length === 0) return [];

  const errors: string[] = [];
  const wantsCore =
    profiles.includes("ucp-core") ||
    profiles.includes("ucp-temporal") ||
    profiles.includes("ucp-secure");

  if (wantsCore) {
    if (!doc.summary?.text) errors.push("ucp-core: summary.text is required");
    for (const [key, source] of Object.entries(doc.sources ?? {})) {
      if (!source.system || !source.type || !source.title) {
        errors.push(`ucp-core: sources[${key}] missing system, type, or title`);
      }
    }
    errors.push(...collectDanglingRefs(doc).map((d) => `ucp-core: dangling source ${d}`));
  }

  if (profiles.includes("ucp-secure")) {
    if (!doc.audience) {
      errors.push("ucp-secure: audience is required");
    } else {
      if (!doc.audience.access_control?.enforced) {
        errors.push("ucp-secure: audience.access_control.enforced must be true");
      }
      if (!doc.audience.access_control?.audit_ref) {
        errors.push("ucp-secure: audience.access_control.audit_ref is required");
      }
    }
  }

  return errors;
}
