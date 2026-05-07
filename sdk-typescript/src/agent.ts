/**
 * Agent — developer-facing surface for emitting protocol messages.
 * Mirrors sdk-python/synapse/agent.py at the operational level.
 */
import type { Bus } from "./bus.js";
import type { InferenceAdapter } from "./adapters/base.js";
import { makeEnvelope } from "./envelope.js";
import type {
  Block,
  Belief,
  Conflict,
  Envelope,
  Intention,
  MessageType,
  Resolution,
} from "./types.js";

const DEFAULT_GATE_MS = 50;

export interface AgentOptions {
  id: string;
  session: string;
  backend: InferenceAdapter;
  subscribes?: string[];
  scopesOwned?: string[];
  tenantId?: string;
  bus: Bus;
}

export class Agent {
  readonly id: string;
  readonly session: string;
  readonly backend: InferenceAdapter;
  readonly subscribes: string[];
  readonly scopesOwned: string[];
  readonly tenantId: string | undefined;
  private readonly bus: Bus;
  private inboxCursor: string = "0";

  constructor(opts: AgentOptions) {
    this.id = opts.id;
    this.session = opts.session;
    this.backend = opts.backend;
    this.subscribes = opts.subscribes ?? [];
    this.scopesOwned = opts.scopesOwned ?? [];
    this.tenantId = opts.tenantId;
    this.bus = opts.bus;
  }

  /** Emit an INTENTION. If `blocking`, wait briefly for CONFLICT signals
   * targeting this intention.
   *
   * Returns [intentionId, conflictsReceived]. If conflicts is non-empty,
   * the caller should pivot/abort instead of proceeding.
   */
  async emitIntention(args: {
    action: Intention["action"];
    scope: string[];
    expected_outcome: string;
    blocking?: boolean;
    estimated_duration_ms?: number;
    uncertainty?: string;
    blocks_others?: string[];
    gateMs?: number;
  }): Promise<[string, Conflict[]]> {
    const payload: Intention = {
      action: args.action,
      scope: args.scope,
      expected_outcome: args.expected_outcome,
      ...(args.blocking !== undefined && { blocking: args.blocking }),
      ...(args.estimated_duration_ms !== undefined && {
        estimated_duration_ms: args.estimated_duration_ms,
      }),
      ...(args.uncertainty !== undefined && { uncertainty: args.uncertainty }),
      ...(args.blocks_others !== undefined && { blocks_others: args.blocks_others }),
    };
    const env = makeEnvelope<Intention>({
      type: "INTENTION",
      agentId: this.id,
      sessionId: this.session,
      payload,
      ...(this.tenantId !== undefined && { tenantId: this.tenantId }),
    });
    await this.bus.publishSession(env);

    if (!args.blocking) return [env.msg_id, []];

    const gateMs = args.gateMs ?? DEFAULT_GATE_MS;
    const deadline = Date.now() + gateMs;
    const conflicts: Conflict[] = [];
    while (Date.now() < deadline) {
      const entries = await this.bus.drainInbox<Conflict>(
        this.id,
        this.inboxCursor,
      );
      for (const [entryId, e] of entries) {
        this.inboxCursor = entryId;
        if (e.type === "CONFLICT" && e.payload.intention_id === env.msg_id) {
          conflicts.push(e.payload);
        }
      }
      if (conflicts.length > 0) break;
      await new Promise((r) => setTimeout(r, 10));
    }
    return [env.msg_id, conflicts];
  }

  /** Emit a RESOLUTION for a previous intention. */
  async emitResolution(args: {
    intentionId: string;
    outcome?: Resolution["outcome"];
    state_diff?: Record<string, unknown>;
    side_effects?: string[];
  }): Promise<string> {
    const payload: Resolution = {
      intention_id: args.intentionId,
      outcome: args.outcome ?? "success",
      ...(args.state_diff !== undefined && { state_diff: args.state_diff }),
      ...(args.side_effects !== undefined && { side_effects: args.side_effects }),
    };
    const env = makeEnvelope<Resolution>({
      type: "RESOLUTION",
      agentId: this.id,
      sessionId: this.session,
      parentMsgId: args.intentionId,
      payload,
      ...(this.tenantId !== undefined && { tenantId: this.tenantId }),
    });
    await this.bus.publishSession(env);
    return env.msg_id;
  }

  /** Emit a BELIEF. */
  async emitBelief(args: {
    key: string;
    value: unknown;
    confidence?: number;
    source?: Belief["source"];
    evidence?: string;
  }): Promise<string> {
    const payload: Belief = {
      key: args.key,
      value: args.value,
      confidence: args.confidence ?? 0.9,
      source: args.source ?? "observed",
      ...(args.evidence !== undefined && { evidence: args.evidence }),
    };
    const env = makeEnvelope<Belief>({
      type: "BELIEF",
      agentId: this.id,
      sessionId: this.session,
      payload,
      ...(this.tenantId !== undefined && { tenantId: this.tenantId }),
    });
    await this.bus.publishSession(env);
    return env.msg_id;
  }

  /** Emit a BLOCK. */
  async emitBlock(args: {
    blocker: string;
    needed: string;
    attempted?: string[];
    urgency?: Block["urgency"];
    topics?: string[];
  }): Promise<string> {
    const payload: Block = {
      blocker: args.blocker,
      needed: args.needed,
      ...(args.attempted !== undefined && { attempted: args.attempted }),
      ...(args.urgency !== undefined && { urgency: args.urgency }),
      ...(args.topics !== undefined && { topics: args.topics }),
    };
    const env = makeEnvelope<Block>({
      type: "BLOCK",
      agentId: this.id,
      sessionId: this.session,
      payload,
      ...(this.tenantId !== undefined && { tenantId: this.tenantId }),
    });
    await this.bus.publishSession(env);
    return env.msg_id;
  }

  /** Drain everything in the inbox since last call. */
  async drainSignals<P = Record<string, unknown>>(): Promise<Envelope<P>[]> {
    const entries = await this.bus.drainInbox<P>(this.id, this.inboxCursor);
    if (entries.length > 0) {
      const last = entries[entries.length - 1];
      if (last) this.inboxCursor = last[0];
    }
    return entries.map(([, e]) => e);
  }

  /** Wait until a signal of the requested type(s) arrives, or timeout. */
  async waitForSignal<P = Record<string, unknown>>(
    types: MessageType[] | undefined,
    timeoutMs = 5000,
  ): Promise<Envelope<P> | null> {
    const deadline = Date.now() + timeoutMs;
    const want = types ? new Set(types) : null;
    while (Date.now() < deadline) {
      const entries = await this.bus.drainInbox<P>(this.id, this.inboxCursor);
      for (const [entryId, env] of entries) {
        this.inboxCursor = entryId;
        if (!want || want.has(env.type)) return env;
      }
      await new Promise((r) => setTimeout(r, 50));
    }
    return null;
  }
}
