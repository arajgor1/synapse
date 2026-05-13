// Shared types — mirror Synapse protocol/v1.0 schemas at JSON wire level.

export type MessageType =
  | "THOUGHT"
  | "INTENTION"
  | "PIVOT"
  | "BELIEF"
  | "BLOCK"
  | "CONFLICT"
  | "RESOLUTION"
  | "COST_REPORT";

export interface Envelope {
  msg_id: string;
  type: MessageType;
  version: string;
  agent_id: string;
  session_id: string;
  task_id?: string;
  parent_msg_id?: string;
  timestamp_ms: number;
  payload: Record<string, unknown>;
  tenant_id?: string;
}

export interface Agent {
  id: string;
  status: "active" | "idle" | "crashed";
  capabilities: {
    backend_id: string;
    tier: "native" | "local_api" | "hosted";
    model_id?: string;
    is_reasoning_model?: boolean;
    avg_overhead_per_signal?: number;
  };
  subscribes: string[];
  scopes_owned: string[];
  last_heartbeat: string | null;
  created_at: string | null;
}

export interface Intention {
  id: string;
  agent_id: string;
  scope: string[];
  action: { tool?: string; args?: Record<string, unknown>; description?: string };
  expected_outcome: string;
  blocking: boolean;
  status: "pending" | "active" | "resolved" | "pivoted";
  created_at: string | null;
  resolved_at: string | null;
}

export interface Belief {
  agent_id: string;
  key: string;
  value: unknown;
  confidence: number;
  source: "observed" | "inferred" | "assumed";
  updated_at: string | null;
}

export interface SnapshotMessage {
  type: "snapshot";
  agents: Agent[];
  intentions: Intention[];
  beliefs: Belief[];
  events: Array<{ entry_id: string; envelope: Envelope }>;
}

export interface EventMessage {
  type: "event";
  entry_id: string;
  envelope: Envelope;
}

export type WSMessage = SnapshotMessage | EventMessage;
