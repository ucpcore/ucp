import { describe, expect, it } from "vitest";
import { join } from "node:path";

import { iterErrors, loads, schema, validate, verifyReferences, UCPValidationError } from "../src/index.js";
import type { UCPackage } from "../src/index.js";
import { SPEC_DIR, exampleData, jsonFiles, loadJson, specAvailable } from "./helpers.js";

describe.skipIf(!specAvailable)("spec suites", () => {
  it("validates the spec example", () => {
    expect(iterErrors(exampleData())).toEqual([]);
  });

  it("accepts every conformance/valid document", () => {
    for (const file of jsonFiles(join(SPEC_DIR, "conformance/valid"))) {
      expect(iterErrors(loadJson(file)), file).toEqual([]);
    }
  });

  it("rejects every conformance/invalid document", () => {
    const files = jsonFiles(join(SPEC_DIR, "conformance/invalid"));
    expect(files.length).toBeGreaterThan(0);
    for (const file of files) {
      expect(() => validate(loadJson(file)), file).toThrow(UCPValidationError);
    }
  });

  it("bundled schema matches the canonical spec schema", () => {
    expect(schema()).toEqual(loadJson(join(SPEC_DIR, "schema/ucp.schema.json")));
  });

  it("verifyReferences is clean on the example and catches dangling keys", () => {
    const pkg = exampleData() as UCPackage;
    expect(verifyReferences(pkg)).toEqual([]);

    const broken = structuredClone(pkg);
    broken.must_know![0].sources = ["missing-key"];
    expect(verifyReferences(broken)).toEqual(["must_know[mk-1]: missing-key"]);
  });
});

it("loads validates by default and can be opted out", () => {
  expect(() => loads("{}")).toThrow(UCPValidationError);
  expect(loads("{}", { validate: false })).toEqual({});
});

it("error messages are informative", () => {
  const errors = iterErrors({ ucp_version: "0.1.0" });
  expect(errors.length).toBeGreaterThan(0);
  expect(errors.join(" ")).toContain("required");
});
