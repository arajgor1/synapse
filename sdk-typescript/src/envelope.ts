import { ulid } from "ulid";
import type { Envelope, MessageType } from "./types.js";

export interface MakeEnvelopeArgs<P> {
  type: MessageType;
  agentId: string;
  sessionId: string;
  payload: P;
  taskId?: string;
  parentMsgId?: string;
  tenantId?: string;
}

/** Construct a Synapse v1.0 envelope with a fresh ULID and current timestamp. */
export function makeEnvelope<P>(args: MakeEnvelopeArgs<P>): Envelope<P> {
  const env: Envelope<P> = {
    msg_id: ulid(),
    type: args.type,
    version: "1.0",
    agent_id: args.agentId,
    session_id: args.sessionId,
    timestamp_ms: Date.now(),
    payload: args.payload,
  };
  if (args.taskId !== undefined) env.task_id = args.taskId;
  if (args.parentMsgId !== undefined) env.parent_msg_id = args.parentMsgId;
  if (args.tenantId !== undefined) env.tenant_id = args.tenantId;
  return env;
}

/** Validate that a value looks like a ULID (26-char Crockford base32). */
export function isUlid(s: string): boolean {
  return /^[0-9A-HJKMNP-TV-Z]{26}$/.test(s);
}
