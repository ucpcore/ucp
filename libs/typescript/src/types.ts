/**
 * TypeScript types for Universal Context Packages (SPEC §4).
 *
 * All types carry an index signature to honor the must-ignore rule
 * (SPEC §6.1): documents from newer spec versions remain assignable,
 * with unknown fields preserved.
 */

export interface Actor {
  id: string;
  display_name?: string;
  role?: string;
  [key: string]: unknown;
}

export interface Generator {
  name: string;
  version?: string;
  url?: string;
  [key: string]: unknown;
}

export interface EntityRef {
  system: string;
  type: string;
  id: string;
  url?: string;
  [key: string]: unknown;
}

export interface Entity {
  ref: EntityRef;
  title: string;
  status?: string;
  assignee?: Actor;
  attributes?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface Summary {
  text: string;
  sources?: string[];
  confidence?: number;
  [key: string]: unknown;
}

export type SalienceMethod = "producer" | "llm" | "graph" | "ranking" | "default";

export interface Claim {
  id: string;
  text: string;
  /** At least one key into the sources registry. Mandatory by spec. */
  sources: string[];
  kind?: string;
  salience?: number;
  salience_method?: SalienceMethod;
  confidence?: number;
  asserted_at?: string;
  valid_from?: string;
  valid_to?: string | null;
  supersedes?: string;
  tags?: string[];
  [key: string]: unknown;
}

export type DecisionStatus = "proposed" | "accepted" | "superseded" | "rejected";

export interface Decision {
  id: string;
  decision: string;
  status: DecisionStatus;
  sources: string[];
  rationale?: string;
  decided_by?: Actor;
  decided_at?: string;
  supersedes?: string;
  [key: string]: unknown;
}

export interface ConflictPosition {
  claim: string;
  sources: string[];
  asserted_at?: string;
  [key: string]: unknown;
}

export interface ResolutionHintObject {
  basis: "recency" | "authority" | "consensus" | "manual";
  note?: string;
  [key: string]: unknown;
}

export interface Conflict {
  id: string;
  description: string;
  positions: ConflictPosition[];
  resolution_hint?: string | ResolutionHintObject;
  severity?: "low" | "medium" | "high";
  [key: string]: unknown;
}

export type ChangeType = "added" | "updated" | "removed" | "status_changed";

export interface Change {
  type: ChangeType;
  summary: string;
  target?: string;
  occurred_at?: string;
  actor?: Actor;
  sources?: string[];
  [key: string]: unknown;
}

export interface ContextDiff {
  since: string;
  changes: Change[];
  baseline?: string;
  [key: string]: unknown;
}

export interface UCPEvent {
  occurred_at: string;
  summary: string;
  actor?: Actor;
  sources?: string[];
  [key: string]: unknown;
}

export interface RelatedObject {
  ref: EntityRef;
  title: string;
  relation?: string;
  salience?: number;
  reason?: string;
  [key: string]: unknown;
}

export interface Source {
  system: string;
  type: string;
  title: string;
  url?: string;
  author?: Actor;
  created_at?: string;
  updated_at?: string;
  content_hash?: string;
  retrieved_at?: string;
  trust?: number;
  excerpt?: string;
  [key: string]: unknown;
}

export interface AccessControl {
  enforced: boolean;
  mechanism?: string;
  checked_at?: string;
  audit_ref?: string;
  [key: string]: unknown;
}

export interface Audience {
  principal: Actor;
  access_control?: AccessControl;
  [key: string]: unknown;
}

export interface Budget {
  token_estimate?: number;
  [key: string]: unknown;
}

export interface UCPackage {
  ucp_version: string;
  id: string;
  generated_at: string;
  generator: Generator;
  entity: Entity;
  sources: Record<string, Source>;

  profiles?: string[];
  language?: string;
  audience?: Audience;
  situation?: string;
  summary?: Summary;
  must_know?: Claim[];
  constraints?: Claim[];
  risks?: Claim[];
  recommended_actions?: Claim[];
  decisions?: Decision[];
  conflicts?: Conflict[];
  context_diff?: ContextDiff;
  history?: UCPEvent[];
  dependencies?: EntityRef[];
  related_objects?: RelatedObject[];
  budget?: Budget;
  extensions?: Record<string, unknown>;
  [key: string]: unknown;
}
