import { readFileSync, readdirSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

// Works in both layouts: the workspace (spec under specs/ucp) and the
// public monorepo (spec files at the repository root).
const candidates = [join(here, "../../../specs/ucp"), join(here, "../../..")];
export const SPEC_DIR =
  candidates.find((c) => existsSync(join(c, "schema/ucp.schema.json"))) ?? candidates[0];

export const specAvailable = existsSync(join(SPEC_DIR, "schema/ucp.schema.json"));

export function loadJson(path: string): unknown {
  return JSON.parse(readFileSync(path, "utf8"));
}

export function jsonFiles(dir: string): string[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((f) => f.endsWith(".json"))
    .sort()
    .map((f) => join(dir, f));
}

export function exampleData(): unknown {
  return loadJson(join(SPEC_DIR, "examples/jira-task.ucp.json"));
}
