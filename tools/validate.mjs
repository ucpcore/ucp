#!/usr/bin/env node
// Validates the UCP schema itself, all examples, and the conformance suite.
// Exit code 0 = everything passes; 1 = failures found.
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import { readFileSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const schema = JSON.parse(readFileSync(join(root, "schema/ucp.schema.json"), "utf8"));

const ajv = new Ajv2020({ strict: true, allErrors: true });
addFormats(ajv);
const validate = ajv.compile(schema); // throws if the schema itself is broken

const jsonFiles = (dir) => {
  try {
    return readdirSync(dir).filter((f) => f.endsWith(".json")).map((f) => join(dir, f));
  } catch {
    return [];
  }
};

let failures = 0;
const check = (file, mustBeValid) => {
  const doc = JSON.parse(readFileSync(file, "utf8"));
  const ok = validate(doc);
  const pass = ok === mustBeValid;
  if (!pass) failures++;
  const label = pass ? "PASS" : "FAIL";
  const expectation = mustBeValid ? "expected valid" : "expected invalid";
  console.log(`${label}  ${file.replace(root + "/", "")}  (${expectation})`);
  if (!pass && !ok) console.log(ajv.errorsText(validate.errors, { separator: "\n       " }));
};

console.log("Schema compiled OK (ajv strict mode, draft 2020-12)\n");
for (const f of jsonFiles(join(root, "examples"))) check(f, true);
for (const f of jsonFiles(join(root, "conformance/valid"))) check(f, true);
for (const f of jsonFiles(join(root, "conformance/invalid"))) check(f, false);

console.log(failures === 0 ? "\nAll checks passed." : `\n${failures} check(s) failed.`);
process.exit(failures === 0 ? 0 : 1);
