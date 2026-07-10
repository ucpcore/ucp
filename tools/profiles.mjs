/** Conformance profile rules (SPEC §5) — beyond JSON Schema. */

function collectSourceRefs(doc) {
  const known = new Set(Object.keys(doc.sources ?? {}));
  const dangling = [];

  const collect = (keys, where) => {
    for (const key of keys ?? []) {
      if (!known.has(key)) dangling.push(`${where}: ${key}`);
    }
  };

  collect(doc.summary?.sources, "summary");
  for (const section of ["must_know", "constraints", "risks", "recommended_actions"]) {
    for (const claim of doc[section] ?? []) {
      collect(claim.sources, `${section}[${claim.id}]`);
    }
  }
  for (const decision of doc.decisions ?? []) {
    collect(decision.sources, `decisions[${decision.id}]`);
  }
  for (const conflict of doc.conflicts ?? []) {
    conflict.positions?.forEach((position, i) => {
      collect(position.sources, `conflicts[${conflict.id}].positions[${i}]`);
    });
  }
  for (const [i, change] of (doc.context_diff?.changes ?? []).entries()) {
    collect(change.sources, `context_diff.changes[${i}]`);
  }
  for (const [i, event] of (doc.history ?? []).entries()) {
    collect(event.sources, `history[${i}]`);
  }
  return dangling;
}

/** @returns {string[]} profile violation messages (empty = ok) */
export function profileErrors(doc) {
  const profiles = doc.profiles ?? [];
  if (profiles.length === 0) return [];

  const errors = [];
  const wantsCore =
    profiles.includes("ucp-core") ||
    profiles.includes("ucp-temporal") ||
    profiles.includes("ucp-secure");

  if (wantsCore) {
    if (!doc.summary?.text) {
      errors.push("ucp-core: summary.text is required");
    }
    for (const [key, source] of Object.entries(doc.sources ?? {})) {
      if (!source.system || !source.type || !source.title) {
        errors.push(`ucp-core: sources[${key}] missing system, type, or title`);
      }
    }
    errors.push(...collectSourceRefs(doc).map((d) => `ucp-core: dangling source ${d}`));
  }

  if (profiles.includes("ucp-secure")) {
    const audience = doc.audience;
    if (!audience) {
      errors.push("ucp-secure: audience is required");
    } else {
      if (!audience.access_control?.enforced) {
        errors.push("ucp-secure: audience.access_control.enforced must be true");
      }
      if (!audience.access_control?.audit_ref) {
        errors.push("ucp-secure: audience.access_control.audit_ref is required");
      }
    }
  }

  if (profiles.includes("ucp-verified")) {
    const receipt = doc.extensions?.["org.ucpcore.receipt"];
    if (receipt?.expected !== true) {
      errors.push("ucp-verified: extensions.org.ucpcore.receipt.expected must be true");
    }
  }

  return errors;
}
