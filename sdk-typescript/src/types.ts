// Mirrors spec/protocol-v1.0/*.schema.json — wire-level types for the eight
// message payloads, the envelope, and the agent-registration handshake.
// Wire format is JSON; types here are the TypeScript view.

export type MessageType =
  | "THOUGHT"
  | "INTENTION"
  | "PIVOT"
  | "BELIEF"
  | "BLOCK"
  | "CONFLICT"
  | "RESOLUTION"
  | "COST_REPORT";

export interface Envelope<P = Record<string, unknown>> {
  msg_id: string;          // ULID
  type: MessageType;
  version: string;         // "1.0"
  agent_id: string;
  session_id: string;
  task_id?: string;
  parent_msg_id?: string;
  timestamp_ms: number;
  payload: P;
  tenant_id?: string;
}

// -----------------------------------------------------------------------------
export interface Intention {
  action:
    | { tool: string; args: Record<string, unknown> }
    | { description: string };
  scope: string[];
  expected_outcome: string;
  estimated_duration_ms?: number;
  blocking?: boolean;
  uncertainty?: string;
  blocks_others?: string[];
}

export interface Thought {
  summary: string;
  raw_excerpt?: string;
  topics?: string[];
  confidence?: number;
}

export interface Pivot {
  from_intention_id: string;
  to_intention: Intention;
  reason: string;
  affects?: string[];
  frees?: string[];
}

export interface Belief {
  key: string;
  value: unknown;
  confidence: number;
  source: "observed" | "inferred" | "assumed";
  evidence?: string;
}

export interface Block {
  blocker: string;
  needed: string;
  attempted?: string[];
  urgency?: "low" | "medium" | "high";
  topics?: string[];
}

export interface ConflictingIntention {
  intention_id: string;
  agent_id: string;
  scope: string[];
  started_at_ms?: number;
}

export interface Conflict {
  intention_id: string;
  conflicting_intentions: ConflictingIntention[];
  kind: "scope_overlap" | "exclusive_claim" | "policy_block" | "dependency_wait";
  overlapping_scopes?: string[];
  suggested_resolution?: "wait" | "pivot" | "narrow_scope" | "coordinate" | "abort";
  rationale?: string;
}

export interface Resolution {
  intention_id: string;
  outcome: "success" | "failure" | "partial";
  state_diff?: Record<string, unknown>;
  side_effects?: string[];
  next_intention_hint?: string;
  error?: { kind: string; message: string; recoverable?: boolean };
}

export interface CostReport {
  signal_id: string;
  mechanism:
    | "inbox_at_decision_point"
    | "native_kv_append"
    | "local_api_context_resume"
    | "hosted_cached_restart"
    | "pre_execution_gate";
  tokens_billed: number;
  tokens_cached?: number;
  wall_clock_ms: number;
  estimated_usd?: number;
}

// -----------------------------------------------------------------------------
export interface BackendCapabilities {
  backend_id: string;
  tier: "native" | "local_api" | "hosted";
  supports_midstream_inject: boolean;
  supports_partial_preservation?: boolean;
  is_reasoning_model?: boolean;
  prompt_cache_available?: boolean;
  avg_overhead_per_signal: number;
  multi_tenant_isolation: "process" | "request_id" | "none";
  model_id?: string;
}

export interface AgentRegistration {
  agent_id: string;
  session_id: string;
  tenant_id?: string;
  subscribes?: string[];
  scopes_owned?: string[];
  capabilities: BackendCapabilities;
}

// -----------------------------------------------------------------------------
// Tenant context — used for request_id-mode multi-tenant isolation
export interface TenantContext {
  tenant_id?: string;
  agent_id?: string;
  session_id?: string;
}

export function tenantsMatch(a: TenantContext, b: TenantContext): boolean {
  return (
    a.tenant_id === b.tenant_id &&
    a.agent_id === b.agent_id &&
    a.session_id === b.session_id
  );
}
