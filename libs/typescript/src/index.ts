/**
 * @ucpcore/core — reference library for the Universal Context Package specification.
 *
 * Spec: https://github.com/contextos/ucp (v0.1.0-draft)
 */
export const SPEC_VERSION = "0.1.0";

export * from "./types.js";
export {
  UCPValidationError,
  iterErrors,
  loads,
  schema,
  validate,
  verifyReferences,
} from "./validate.js";
export { DROP_ORDER, estimateTokens, render, type RenderOptions } from "./render.js";
