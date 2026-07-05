import { describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { estimateTokens, render } from "../src/index.js";
import type { UCPackage } from "../src/index.js";
import { SPEC_DIR, exampleData, specAvailable } from "./helpers.js";

const here = dirname(fileURLToPath(import.meta.url));

describe.skipIf(!specAvailable)("canonical rendering", () => {
  const pkg = () => exampleData() as UCPackage;

  it("renders sections in canonical order", () => {
    const text = render(pkg());
    const markers = [
      "# Context: Migrate payment webhooks to v2 API",
      "## What changed",
      "## Summary",
      "## Must know",
      "## Constraints",
      "## Risks",
      "## Decisions",
      "## Conflicts",
      "## Recommended actions",
      "## Timeline",
      "## Related",
      "## Sources",
    ];
    const positions = markers.map((m) => text.indexOf(m));
    expect(positions).toEqual([...positions].sort((a, b) => a - b));
    expect(positions.every((p) => p >= 0)).toBe(true);
  });

  it("is deterministic", () => {
    expect(render(pkg())).toEqual(render(pkg()));
  });

  it("respects a token budget and protects the core", () => {
    const full = render(pkg());
    const budget = estimateTokens(full) - 100;
    const trimmed = render(pkg(), { tokenBudget: budget });
    expect(estimateTokens(trimmed)).toBeLessThanOrEqual(budget);
    expect(trimmed.length).toBeLessThan(full.length);

    const tiny = render(pkg(), { tokenBudget: 1 });
    expect(tiny).toContain("## Summary");
    expect(tiny).toContain("## Conflicts");
    expect(tiny).toContain("## What changed");
    expect(tiny).not.toContain("## Timeline");
  });

  it("drops least salient content first", () => {
    const full = render(pkg());
    const trimmed = render(pkg(), { tokenBudget: estimateTokens(full) - 30 });
    expect(trimmed).toContain("HMAC-SHA256"); // salience 0.97 survives
  });
});

const pythonBin = join(here, "../../ucp-py/.venv/bin/python");

describe.skipIf(!specAvailable || !existsSync(pythonBin))("cross-implementation parity", () => {
  it("renders the spec example byte-identically to the Python reference library", () => {
    const tsText = render(exampleData() as UCPackage);
    const pyText = execFileSync(
      pythonBin,
      [
        "-c",
        "import ucp, sys; sys.stdout.write(ucp.render(ucp.load(sys.argv[1])))",
        join(SPEC_DIR, "examples/jira-task.ucp.json"),
      ],
      { encoding: "utf8" }
    );
    expect(tsText).toEqual(pyText);
  });
});
