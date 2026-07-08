#!/usr/bin/env node
// Validates UCP + Usage Receipt schemas, examples, and conformance suites.
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import { readFileSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { profileErrors } from "./profiles.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const ucpSchema = JSON.parse(readFileSync(join(root, "schema/ucp.schema.json"), "utf8"));
const receiptSchema = JSON.parse(
  readFileSync(join(root, "schema/usage-receipt.schema.json"), "utf8")
);

const ajv = new Ajv2020({ strict: true, allErrors: true });
addFormats(ajv);
const validateUcp = ajv.compile(ucpSchema);
const validateReceipt = ajv.compile(receiptSchema);

const jsonFiles = (dir) => {
  try {
    return readdirSync(dir).filter((f) => f.endsWith(".json")).map((f) => join(dir, f));
  } catch {
    return [];
  }
};

let failures = 0;

const checkUcp = (file, mustBeValid) => {
  const doc = JSON.parse(readFileSync(file, "utf8"));
  const schemaOk = validateUcp(doc);
  const profiles = profileErrors(doc);
  const ok = schemaOk && profiles.length === 0;
  const pass = ok === mustBeValid;
  if (!pass) failures++;
  const label = pass ? "PASS" : "FAIL";
  console.log(`${label}  ${file.replace(root + "/", "")}  (ucp, ${mustBeValid ? "valid" : "invalid"})`);
  if (!pass) {
    if (!schemaOk) console.log(ajv.errorsText(validateUcp.errors, { separator: "\n       " }));
    if (mustBeValid && profiles.length) {
      console.log("       profile:", profiles.join("\n       profile: "));
    }
    if (!mustBeValid && schemaOk && profiles.length) {
      console.log("       profile:", profiles.join("\n       profile: "));
    }
  }
};

const checkReceipt = (file, mustBeValid) => {
  const doc = JSON.parse(readFileSync(file, "utf8"));
  const ok = validateReceipt(doc);
  const pass = ok === mustBeValid;
  if (!pass) failures++;
  const label = pass ? "PASS" : "FAIL";
  console.log(
    `${label}  ${file.replace(root + "/", "")}  (receipt, ${mustBeValid ? "valid" : "invalid"})`
  );
  if (!pass && !ok) {
    console.log(ajv.errorsText(validateReceipt.errors, { separator: "\n       " }));
  }
};

console.log("Schemas compiled OK (ajv strict mode, draft 2020-12)\n");

console.log("--- UCP packages ---");
for (const f of jsonFiles(join(root, "examples")).filter((p) => p.endsWith(".ucp.json"))) {
  checkUcp(f, true);
}
for (const f of jsonFiles(join(root, "conformance/valid"))) checkUcp(f, true);
for (const f of jsonFiles(join(root, "conformance/invalid"))) checkUcp(f, false);

console.log("\n--- Usage Receipts ---");
for (const f of jsonFiles(join(root, "examples")).filter((p) => p.endsWith(".receipt.json"))) {
  checkReceipt(f, true);
}
for (const f of jsonFiles(join(root, "conformance/receipt/valid"))) checkReceipt(f, true);
for (const f of jsonFiles(join(root, "conformance/receipt/invalid"))) checkReceipt(f, false);

console.log(failures === 0 ? "\nAll checks passed." : `\n${failures} check(s) failed.`);
process.exit(failures === 0 ? 0 : 1);
