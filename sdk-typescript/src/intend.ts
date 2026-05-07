/**
 * `synapse.intend()` — TypeScript port of sdk-python/synapse/intend.py.
 *
 * Wraps a tool dispatch with INTENTION emission, conflict detection, and
 * RESOLUTION on exit. Works in any TS codebase regardless of which agent
 * framework is in use.
 *
 * Two public APIs are shipped:
 *
 *   1) `intend()` returns a disposable handle (TS 5.2+ `await using`):
 *
 *      ```ts
 *      await using i = await synapse.intend({
 *        scope: ["repo.fs.auth.ts:w"],
 *        agent: "code-reviewer",
 *        expectedOutcome: "fix CVE-2026-1234",
 *      });
 *      if (i.hasConflicts) await i.pivot();
 *      i.setStateDiff({ linesChanged: 47 });
 *      // RESOLUTION emitted automatically when `i` falls out of scope.
 *      ```
 *
 *   2) `intendWith(opts, async (i) => { ... })` — callback wrapper that
 *      works on older TS / runtimes without explicit-resource-management.
 */
import { Agent } from "./agent.js";
import { Bus } from "./bus.js";
import { MockAdapter } from "./adapters/mock.js";
import {
  MergeDecision,
  MergePolicy,
  SynapseConflict,
  type MergeAction,
} from "./policies/base.js";
import {
  criticalScopeMatch,
  normalizeCriticalScopes,
} from "./policies/critical.js";
import { resolvePolicy } from "./policies/registry.js";
import type { Conflict } from "./types.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
export type Outcome = "success" | "failure" | "partial";

export interface IntendOptions {
  scope: string[];
  agent: string;
  session?: string;
  expectedOutcome?: string;
  blocking?: boolean;
  gateMs?: number;
  estimatedDurationMs?: number;
  uncertainty?: string;
  /** A `MergePolicy` instance, a string name, or null/undefined to fall back
   * to the install()-time default. */
  mergePolicy?: MergePolicy | string | null;
  criticalScopes?: string[];
  /** Required for AutoMergePolicy; optional otherwise. */
  proposedAction?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// IntentionHandle — mirrors Python `IntentionHandle` field-for-field.
// ---------------------------------------------------------------------------
export class IntentionHandle implements AsyncDisposable {
  intentionId: string;
  scope: string[];
  agentId: string;
  sessionId: string;
  conflicts: Conflict[];

  // Caller-mutable
  stateDiff: Record<string, unknown>;
  sideEffects: string[];
  outcome: Outcome;
  errorMessage?: string;

  // Filled by AutoMergePolicy
  mergedAction?: Record<string, unknown> | null;
  policyRationale?: string;
  aborted: boolean;

  // Filled by belief auto-extractor (v0.2 week 5)
  beliefsEmitted: Array<Record<string, unknown>>;
  divergences: Array<Record<string, unknown>>;

  // Internal — set by intend() so dispose can finalize.
  private _agent: Agent | null = null;
  private _emitBeliefs: boolean = false;
  private _disposed: boolean = false;
  private _toolArgs: Record<string, unknown> = {};

  constructor(args: {
    intentionId: string;
    scope: string[];
    agentId: string;
    sessionId: string;
  }) {
    this.intentionId = args.intentionId;
    this.scope = [...args.scope];
    this.agentId = args.agentId;
    this.sessionId = args.sessionId;
    this.conflicts = [];
    this.stateDiff = {};
    this.sideEffects = [];
    this.outcome = "success";
    this.aborted = false;
    this.beliefsEmitted = [];
    this.divergences = [];
  }

  get hasConflicts(): boolean {
    return this.conflicts.length > 0;
  }

  setStateDiff(diff: Record<string, unknown>): void {
    Object.assign(this.stateDiff, diff);
  }

  addSideEffect(effect: string): void {
    this.sideEffects.push(effect);
  }

  markFailed(message: string = ""): void {
    this.outcome = "failure";
    if (message) this.errorMessage = message.slice(0, 200);
  }

  /** Caller-driven pivot hook. Default impl is a no-op marker; framework
   * adapters override or callers re-prompt their LLM. */
  async pivot(): Promise<void> {
    /* no-op default */
  }

  /** Internal — used by `intend()` to wire up finalization. */
  _bind(args: {
    agent: Agent | null;
    emitBeliefs: boolean;
    toolArgs: Record<string, unknown>;
  }): void {
    this._agent = args.agent;
    this._emitBeliefs = args.emitBeliefs;
    this._toolArgs = args.toolArgs;
  }

  async [Symbol.asyncDispose](): Promise<void> {
    if (this._disposed) return;
    this._disposed = true;
    await this._finalize();
  }

  /** Public alias — useful for callback users who want to force-finalize. */
  async dispose(): Promise<void> {
    return this[Symbol.asyncDispose]();
  }

  private async _finalize(): Promise<void> {
    const agent = this._agent;

    if (agent !== null && this.intentionId && !this.aborted) {
      try {
        let sd: Record<string, unknown> = { ...this.stateDiff };
        if (Object.keys(sd).length === 0 && this.errorMessage) {
          sd = { error: this.errorMessage };
        }
        if (this.policyRationale) {
          sd = { ...sd, policy_rationale: this.policyRationale };
        }
        await agent.emitResolution({
          intentionId: this.intentionId,
          outcome: this.outcome,
          state_diff: sd,
          ...(this.sideEffects.length > 0
            ? { side_effects: this.sideEffects }
            : {}),
        });
      } catch (e) {
        // best-effort
        // eslint-disable-next-line no-console
        console.warn("synapse.intend: emit_resolution failed", e);
      }
    }

    if (
      this._emitBeliefs &&
      !this.aborted &&
      this.outcome === "success" &&
      Object.keys(this.stateDiff).length > 0
    ) {
      await _autoEmitAndDetect({ handle: this, toolArgs: this._toolArgs });
    }
  }
}

// ---------------------------------------------------------------------------
// Module-level runtime — mirrors Python `_runtime` dict.
// ---------------------------------------------------------------------------
export interface SynapseRuntime {
  bus?: Bus;
  busUrl?: string;
  state?: unknown; // StateGraph not yet ported
  stateDsn?: string;
  mode?: "offline" | "live";
  connected?: boolean;
  agents?: Map<string, Agent>;
  policy_defaults?: {
    merge_policy?: MergePolicy | null;
    critical_scopes?: string[];
    emit_beliefs_from_tool_results?: boolean;
  };
}

/** Module-level runtime singleton. Exported for tests + cross-module use. */
export const _runtime: SynapseRuntime = {};

/** Idempotent runtime setup — `install()` configures explicitly,
 * `intend()` falls back to env vars. */
export function _getOrInitRuntime(opts: {
  busUrl?: string;
  stateDsn?: string;
} = {}): SynapseRuntime {
  if (_runtime.bus !== undefined) return _runtime;

  const busUrl = opts.busUrl ?? process.env["SYNAPSE_REDIS_URL"];
  const stateDsn = opts.stateDsn ?? process.env["SYNAPSE_POSTGRES_DSN"];

  if (!busUrl) {
    _runtime.mode = "offline";
    return _runtime;
  }

  _runtime.bus = new Bus({ url: busUrl });
  _runtime.busUrl = busUrl;
  if (stateDsn !== undefined) _runtime.stateDsn = stateDsn;
  _runtime.agents = new Map();
  _runtime.mode = "live";
  _runtime.connected = false;
  return _runtime;
}

async function _ensureConnected(): Promise<SynapseRuntime> {
  const rt = _getOrInitRuntime();
  if (rt.mode === "offline") return rt;
  if (rt.connected) return rt;

  const bus = rt.bus;
  if (bus !== undefined) {
    await bus.connect();
  }
  rt.connected = true;
  return rt;
}

/** Alias for `_getOrInitRuntime` so consumers can also `import { getOrInitRuntime }`. */
export const getOrInitRuntime = _getOrInitRuntime;

/** Cached per-(session, agent) Agent factory. Returns null in offline mode. */
export async function _getAgent(
  agentId: string,
  sessionId: string,
): Promise<Agent | null> {
  // Cache check first — lets tests pre-populate fake agents without a bus.
  const cacheKey = `${sessionId}::${agentId}`;
  if (_runtime.agents) {
    const cached = _runtime.agents.get(cacheKey);
    if (cached) return cached;
  }

  const rt = await _ensureConnected();
  if (rt.mode === "offline" || rt.bus === undefined) return null;

  const agents = rt.agents ?? new Map<string, Agent>();
  if (!rt.agents) rt.agents = agents;

  const cached = agents.get(cacheKey);
  if (cached) return cached;

  const agent = new Agent({
    id: agentId,
    session: sessionId,
    backend: new MockAdapter(),
    bus: rt.bus,
    subscribes: [],
  });
  agents.set(cacheKey, agent);
  return agent;
}

/** Alias for `_getAgent` so consumers can also `import { getAgent }`. */
export const getAgent = _getAgent;

// (Policy resolution lives in ./policies/registry.ts — `resolvePolicy`.)

// ---------------------------------------------------------------------------
// The main entry point — returns a disposable IntentionHandle.
// ---------------------------------------------------------------------------
export async function intend(opts: IntendOptions): Promise<IntentionHandle> {
  const sessionId =
    opts.session ??
    process.env["SYNAPSE_SESSION_ID"] ??
    "default_session";

  const handle = new IntentionHandle({
    intentionId: "",
    scope: opts.scope,
    agentId: opts.agent,
    sessionId,
  });

  const installDefaults = _runtime.policy_defaults ?? {};
  let policy = resolvePolicy(opts.mergePolicy ?? null);
  if (policy === null) {
    policy = resolvePolicy(installDefaults.merge_policy ?? null);
  }
  const critScopes = normalizeCriticalScopes(
    opts.criticalScopes !== undefined
      ? opts.criticalScopes
      : installDefaults.critical_scopes,
  );
  const emitBeliefs = !!installDefaults.emit_beliefs_from_tool_results;

  let synAgent: Agent | null = null;
  try {
    synAgent = await _getAgent(opts.agent, sessionId);
  } catch (e) {
    console.warn("synapse.intend: failed to set up agent; offline mode", e);
  }

  if (synAgent !== null) {
    try {
      const expectedOutcome = opts.expectedOutcome ?? `intend:${opts.agent}`;
      const [intentionId, conflicts] = await synAgent.emitIntention({
        action: { description: expectedOutcome },
        scope: [...opts.scope],
        expected_outcome: opts.expectedOutcome ?? "tool dispatch",
        blocking: opts.blocking ?? true,
        gateMs: opts.gateMs ?? 50,
        ...(opts.estimatedDurationMs !== undefined
          ? { estimated_duration_ms: opts.estimatedDurationMs }
          : {}),
        ...(opts.uncertainty !== undefined
          ? { uncertainty: opts.uncertainty }
          : {}),
      });
      handle.intentionId = intentionId;
      handle.conflicts = conflicts ?? [];
    } catch (e) {
      console.warn(
        "synapse.intend: emit_intention failed; proceeding anyway",
        e,
      );
    }
  }

  // Apply MergePolicy if conflicts surfaced.
  if (handle.hasConflicts) {
    // 1) critical_scopes hard-block first.
    const match = criticalScopeMatch(handle.scope, critScopes);
    if (match !== null) {
      const rationale =
        `Critical scope match: ${JSON.stringify(match)} forced ABORT on ` +
        `${JSON.stringify(handle.scope)}. ` +
        `${handle.conflicts.length} conflicting intention(s).`;
      handle.aborted = true;
      handle.policyRationale = rationale;
      handle.markFailed(rationale);
      if (synAgent !== null && handle.intentionId) {
        try {
          await synAgent.emitResolution({
            intentionId: handle.intentionId,
            outcome: "failure",
            state_diff: { error: rationale, policy: "critical_scope" },
          });
        } catch {
          /* swallow */
        }
      }
      throw new SynapseConflict(handle.conflicts, handle.scope, rationale);
    }

    // 2) configured policy.
    if (policy !== null) {
      let action: MergeAction | null = null;
      try {
        action = await policy.resolve(
          handle,
          handle.conflicts,
          opts.proposedAction,
        );
      } catch (e) {
        console.warn("synapse.intend: merge_policy.resolve raised", e);
        action = null;
      }
      if (action !== null) {
        handle.policyRationale = action.rationale;
        if (action.decision === MergeDecision.ABORT) {
          handle.aborted = true;
          handle.markFailed(action.rationale);
          if (synAgent !== null && handle.intentionId) {
            try {
              await synAgent.emitResolution({
                intentionId: handle.intentionId,
                outcome: "failure",
                state_diff: {
                  error: action.rationale,
                  policy: policy.name,
                },
              });
            } catch {
              /* swallow */
            }
          }
          throw new SynapseConflict(
            handle.conflicts,
            handle.scope,
            action.rationale,
          );
        } else if (action.decision === MergeDecision.MERGED) {
          handle.mergedAction = action.mergedAction ?? null;
        } else if (action.decision === MergeDecision.WAIT) {
          const ms = action.waitTimeoutMs ?? 100;
          await new Promise((r) => setTimeout(r, ms));
        }
        // MergeDecision.PROCEED needs no action.
      }
    }
  }

  handle._bind({
    agent: synAgent,
    emitBeliefs,
    toolArgs: opts.proposedAction ?? {},
  });

  return handle;
}

// ---------------------------------------------------------------------------
// Callback wrapper — for environments without `await using`.
// ---------------------------------------------------------------------------
export async function intendWith<T>(
  opts: IntendOptions,
  fn: (handle: IntentionHandle) => Promise<T>,
): Promise<T> {
  const handle = await intend(opts);
  try {
    return await fn(handle);
  } catch (e) {
    handle.markFailed((e as Error)?.message ?? String(e));
    throw e;
  } finally {
    await handle.dispose();
  }
}

// ---------------------------------------------------------------------------
// Belief auto-extraction stub — A3 ships the real one. Best-effort.
// ---------------------------------------------------------------------------
async function _autoEmitAndDetect(args: {
  handle: IntentionHandle;
  toolArgs: Record<string, unknown>;
}): Promise<void> {
  try {
    // Lazy import — beliefs/api.ts is owned by A3 and may not exist yet.
    const mod = (await import("./beliefs/api.js" as string).catch(
      () => null,
    )) as
      | {
          emitBelief?: (...x: unknown[]) => Promise<unknown>;
          extractBeliefsWithLLM?: (...x: unknown[]) => Promise<unknown[]>;
        }
      | null;
    if (!mod || !mod.emitBelief || !mod.extractBeliefsWithLLM) return;

    const sd = args.handle.stateDiff ?? {};
    const output =
      (sd["content"] as string | undefined) ??
      (sd["output"] as string | undefined) ??
      (sd["output_preview"] as string | undefined) ??
      JSON.stringify(sd).slice(0, 1500);

    const facts = (await mod.extractBeliefsWithLLM({
      tool_name: (args.toolArgs["tool"] as string | undefined) ?? "tool_call",
      tool_args: args.toolArgs,
      output,
    })) as Array<{
      key: string;
      value: unknown;
      confidence: number;
      evidence?: string;
    }>;

    for (const fact of facts) {
      args.handle.beliefsEmitted.push({
        key: fact.key,
        value: fact.value,
        confidence: fact.confidence,
        evidence: fact.evidence,
      });
      const div = (await mod.emitBelief({
        agent: args.handle.agentId,
        session: args.handle.sessionId,
        key: fact.key,
        value: fact.value,
        confidence: fact.confidence,
        source: "observed",
        evidence: fact.evidence,
        detect_divergence: true,
      })) as { to_dict?: () => Record<string, unknown> } | null;
      if (div && typeof div.to_dict === "function") {
        args.handle.divergences.push(div.to_dict());
      }
    }
  } catch (e) {
    console.warn("synapse: auto-extract beliefs failed", e);
  }
}

// ---------------------------------------------------------------------------
// Cleanup — used by tests + by `synapse.install` shutdown.
// ---------------------------------------------------------------------------
export async function shutdown(): Promise<void> {
  const rt = _runtime;
  if (rt.connected) {
    if (rt.bus) {
      try {
        await rt.bus.close();
      } catch {
        /* swallow */
      }
    }
  }
  // Clear keys (preserve identity of `_runtime` for re-imports/tests).
  for (const k of Object.keys(rt) as Array<keyof SynapseRuntime>) {
    delete (rt as Record<string, unknown>)[k];
  }
}
