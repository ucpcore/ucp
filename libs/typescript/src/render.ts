/**
 * Canonical CommonMark rendering of a UCP package (SPEC §7).
 *
 * Deterministic and behavior-identical to the Python reference library:
 * the same package renders to the same prompt. Under a token budget, items
 * drop in ascending-salience order within sections, sections drop in the
 * order of SPEC §7.2, and summary/conflicts/context_diff survive longest.
 */
import type {
  Claim,
  Conflict,
  RelatedObject,
  ResolutionHintObject,
  Source,
  UCPackage,
  UCPEvent,
} from "./types.js";

/** Sections whose items may be dropped under a token budget, cheapest first. */
export const DROP_ORDER = [
  "history",
  "related_objects",
  "recommended_actions",
  "risks",
  "constraints",
  "decisions",
  "must_know",
] as const;

type DroppableSection = (typeof DROP_ORDER)[number];

const SECTION_TITLES: Record<string, string> = {
  must_know: "Must know",
  constraints: "Constraints",
  risks: "Risks",
  recommended_actions: "Recommended actions",
};

/** Fast token estimate (~4 chars per token). Good enough for budgeting. */
export function estimateTokens(text: string): number {
  return Math.max(1, Math.ceil(text.length / 4));
}

function date(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 10) : "";
}

function sourceLabels(keys: string[] | undefined, sources: Record<string, Source>): string {
  return (keys ?? []).map((k) => sources[k]?.title ?? k).join(", ");
}

function formatResolutionHint(
  hint: string | ResolutionHintObject | undefined
): string | undefined {
  if (hint === undefined) return undefined;
  if (typeof hint === "string") return hint;
  return hint.note ? `${hint.basis}: ${hint.note}` : hint.basis;
}

function claimLine(claim: Claim, sources: Record<string, Source>): string {
  return `- ${claim.text} [source: ${sourceLabels(claim.sources, sources)}]`;
}

/**
 * Descending salience; unspecified salience sorts last, original order kept.
 * Works for any item type: objects without a salience field (e.g. UCPEvent)
 * are treated as unspecified.
 */
function bySalienceDesc<T extends object>(items: readonly T[]): T[] {
  const salience = (item: T): number =>
    (item as { salience?: number }).salience ?? -1;
  return items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => salience(b.item) - salience(a.item) || a.index - b.index)
    .map(({ item }) => item);
}

function renderOnce(pkg: UCPackage): string {
  const src = pkg.sources;
  const out: string[] = [];

  const ref = pkg.entity.ref;
  out.push(`# Context: ${pkg.entity.title}`);
  out.push(`> ${ref.system}/${ref.type} ${ref.id}` + (ref.url ? ` — ${ref.url}` : ""));
  if (pkg.entity.status) out.push(`> Status: ${pkg.entity.status}`);
  out.push("");

  if (pkg.context_diff) {
    out.push("## What changed");
    out.push(`Since ${date(pkg.context_diff.since)}:`);
    if (pkg.context_diff.changes.length > 0) {
      for (const change of pkg.context_diff.changes) {
        const when = change.occurred_at ? `[${date(change.occurred_at)}] ` : "";
        out.push(`- ${when}${change.summary}`);
      }
    } else {
      out.push("- Nothing changed.");
    }
    out.push("");
  }

  if (pkg.summary) {
    out.push("## Summary", pkg.summary.text, "");
  }

  for (const field of ["must_know", "constraints", "risks"] as const) {
    const claims = pkg[field] ?? [];
    if (claims.length > 0) {
      out.push(`## ${SECTION_TITLES[field]}`);
      for (const claim of bySalienceDesc(claims)) out.push(claimLine(claim, src));
      out.push("");
    }
  }

  if ((pkg.decisions ?? []).length > 0) {
    out.push("## Decisions");
    for (const decision of pkg.decisions!) {
      let line = `- ${decision.decision}`;
      if (decision.rationale) line += ` — ${decision.rationale}`;
      const meta =
        decision.status + (decision.decided_at ? `, ${date(decision.decided_at)}` : "");
      out.push(`${line} (${meta})`);
    }
    out.push("");
  }

  if ((pkg.conflicts ?? []).length > 0) {
    out.push("## Conflicts");
    for (const conflict of pkg.conflicts!) {
      out.push(`- ${conflict.description}`);
      for (const position of conflict.positions) {
        const when = position.asserted_at ? ` (${date(position.asserted_at)})` : "";
        out.push(`  - ${position.claim}${when} [source: ${sourceLabels(position.sources, src)}]`);
      }
      const hint = formatResolutionHint(conflict.resolution_hint);
      if (hint) out.push(`  - Hint: ${hint}`);
    }
    out.push("");
  }

  if ((pkg.recommended_actions ?? []).length > 0) {
    out.push(`## ${SECTION_TITLES.recommended_actions}`);
    for (const claim of bySalienceDesc(pkg.recommended_actions!)) {
      out.push(claimLine(claim, src));
    }
    out.push("");
  }

  if ((pkg.history ?? []).length > 0) {
    out.push("## Timeline");
    const events = [...pkg.history!].sort((a, b) =>
      a.occurred_at.localeCompare(b.occurred_at)
    );
    for (const event of events) out.push(`- [${date(event.occurred_at)}] ${event.summary}`);
    out.push("");
  }

  if ((pkg.related_objects ?? []).length > 0) {
    out.push("## Related");
    for (const related of bySalienceDesc(pkg.related_objects!)) {
      let line = `- ${related.title}`;
      if (related.relation) line += ` (${related.relation})`;
      if (related.reason) line += ` — ${related.reason}`;
      out.push(line);
    }
    out.push("");
  }

  out.push("## Sources");
  Object.values(pkg.sources).forEach((source, i) => {
    out.push(`${i + 1}. ${source.title}` + (source.url ? ` — ${source.url}` : ""));
  });

  return out.join("\n").trim() + "\n";
}

export interface RenderOptions {
  tokenBudget?: number;
  countTokens?: (text: string) => number;
}

/** Render a package to canonical CommonMark, optionally under a token budget. */
export function render(pkg: UCPackage, options: RenderOptions = {}): string {
  const { tokenBudget, countTokens = estimateTokens } = options;
  let text = renderOnce(pkg);
  if (tokenBudget === undefined || countTokens(text) <= tokenBudget) return text;

  const trimmed: UCPackage = structuredClone(pkg);
  for (const section of DROP_ORDER) {
    while ((trimmed[section] ?? []).length > 0) {
      // Drop the least salient item (end of the descending-ordered list,
      // which is also the render order).
      const ordered = bySalienceDesc(
        trimmed[section] as Array<Claim | RelatedObject | UCPEvent>
      );
      ordered.pop();
      (trimmed as Record<DroppableSection, unknown>)[section] = ordered;
      text = renderOnce(trimmed);
      if (countTokens(text) <= tokenBudget) return text;
    }
  }
  // Budget cannot be met by dropping optional sections; the protected core
  // (summary, conflicts, context_diff) is returned as-is by design.
  return text;
}
