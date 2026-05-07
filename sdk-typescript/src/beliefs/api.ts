/**
 * Public-facing belief API.
 *
 * Ported from sdk-python/synapse/beliefs/api.py.
 *
 *   emitBelief()        → emit + persist + run live divergence detection.
 *   listDivergences()   → all current divergences for a session.
 *   divergencesForKey() → convenience wrapper for one key.
 */
import {
  type AgentBelief,
  beliefsFromDbRows,
  detectDivergences,
} from "./divergence.js";
import {
  type LiveDivergenceResult,
  buildRationale,
  detectLiveDivergence,
  makeLiveDivergenceResult,
} from "./liveDetector.js";

export type { LiveDivergenceResult } from "./liveDetector.js";

interface RuntimeLike {
  state?: { pool?: PoolLike } | null;
  get?: (key: string) => unknown;
}

interface PoolLike {
  fetch?: (q: string, ...args: unknown[]) => Promise<unknown[]>;
  execute?: (q: string, ...args: unknown[]) => Promise<unknown>;
}

interface AgentLike {
  emitBelief(args: {
    key: string;
    value: unknown;
    confidence?: number;
    source?: string;
    evidence?: string;
  }): Promise<unknown>;
}

async function loadRuntime(): Promise<unknown> {
  try {
    const mod = (await import("../intend.js")) as Record<string, unknown>;
    const fn =
      (mod["_getOrInitRuntime"] as (() => unknown) | undefined) ??
      (mod["getOrInitRuntime"] as (() => unknown) | undefined);
    return fn ? fn() : null;
  } catch {
    return null;
  }
}

async function loadAgent(agentId: string, sessionId: string): Promise<AgentLike | null> {
  try {
    const mod = (await import("../intend.js")) as Record<string, unknown>;
    const fn =
      (mod["_getAgent"] as
        | ((id: string, sid: string) => Promise<unknown>)
        | undefined) ??
      (mod["getAgent"] as
        | ((id: string, sid: string) => Promise<unknown>)
        | undefined);
    if (typeof fn !== "function") return null;
    const a = await fn(agentId, sessionId);
    if (a === null || a === undefined || typeof a !== "object") return null;
    if (typeof (a as Record<string, unknown>)["emitBelief"] !== "function") {
      return null;
    }
    return a as AgentLike;
  } catch {
    return null;
  }
}

function readState(rt: unknown): { pool: PoolLike } | null {
  if (rt === null || typeof rt !== "object") return null;
  const r = rt as RuntimeLike;
  let state: unknown;
  if (typeof r.get === "function") state = r.get("state");
  else state = (r as Record<string, unknown>)["state"];
  if (state === null || state === undefined || typeof state !== "object") {
    return null;
  }
  const pool = (state as Record<string, unknown>)["pool"];
  if (pool === null || pool === undefined || typeof pool !== "object") {
    return null;
  }
  return { pool: pool as PoolLike };
}

export interface EmitBeliefArgs {
  agent: string;
  key: string;
  value: unknown;
  session?: string;
  confidence?: number;
  source?: string;
  evidence?: string;
  detectDivergence?: boolean;
}

/**
 * Emit a BELIEF + run live divergence detection.
 *
 * Returns LiveDivergenceResult if a divergence was detected on this key,
 * null otherwise. Returns null in offline mode (no runtime / no state).
 */
export async function emitBelief(
  args: EmitBeliefArgs,
): Promise<LiveDivergenceResult | null> {
  const sessionId =
    args.session ??
    (typeof process !== "undefined"
      ? process.env?.["SYNAPSE_SESSION_ID"]
      : undefined) ??
    "default_session";

  const confidence = args.confidence ?? 0.9;
  const source = args.source ?? "observed";
  const detect = args.detectDivergence !== false;

  const synAgent = await loadAgent(args.agent, sessionId);
  if (synAgent === null) return null; // offline mode

  try {
    const emitArgs: {
      key: string;
      value: unknown;
      confidence?: number;
      source?: string;
      evidence?: string;
    } = {
      key: args.key,
      value: args.value,
      confidence,
      source,
    };
    if (args.evidence !== undefined) emitArgs.evidence = args.evidence;
    await synAgent.emitBelief(emitArgs);
  } catch {
    return null;
  }

  // Persist directly to PG so live detection sees it sub-second.
  const persistArgs: {
    agent: string;
    sessionId: string;
    key: string;
    value: unknown;
    confidence: number;
    source: string;
    evidence?: string;
  } = {
    agent: args.agent,
    sessionId,
    key: args.key,
    value: args.value,
    confidence,
    source,
  };
  if (args.evidence !== undefined) persistArgs.evidence = args.evidence;
  await persistBeliefToState(persistArgs);

  if (!detect) return null;
  return detectLiveDivergence({
    sessionId,
    justEmittedKey: args.key,
  });
}

async function persistBeliefToState(args: {
  agent: string;
  sessionId: string;
  key: string;
  value: unknown;
  confidence: number;
  source: string;
  evidence?: string;
}): Promise<void> {
  const rt = await loadRuntime();
  const state = readState(rt);
  if (state === null) return;
  const exec = state.pool.execute;
  if (typeof exec !== "function") return;
  try {
    await exec.call(
      state.pool,
      `
      INSERT INTO beliefs (agent_id, session_id, tenant_id, key, value,
                            confidence, source, evidence, updated_at)
      VALUES ($1, $2, NULL, $3, $4::jsonb, $5, $6, $7, now())
      ON CONFLICT (agent_id, key) DO UPDATE SET
        value = EXCLUDED.value,
        confidence = EXCLUDED.confidence,
        source = EXCLUDED.source,
        evidence = EXCLUDED.evidence,
        updated_at = now(),
        session_id = EXCLUDED.session_id
      `,
      args.agent,
      args.sessionId,
      args.key,
      JSON.stringify(args.value),
      args.confidence,
      args.source,
      args.evidence ?? null,
    );
  } catch {
    // best-effort; ignore.
  }
}

/** Return all current belief divergences for the session. */
export async function listDivergences(
  sessionId?: string,
): Promise<LiveDivergenceResult[]> {
  const rt = await loadRuntime();
  const state = readState(rt);
  if (state === null) return [];

  const sid =
    sessionId ??
    (typeof process !== "undefined"
      ? process.env?.["SYNAPSE_SESSION_ID"]
      : undefined);
  if (!sid) return [];

  const fetchFn = state.pool.fetch;
  if (typeof fetchFn !== "function") return [];

  let rows: unknown[];
  try {
    rows = await fetchFn.call(
      state.pool,
      "SELECT agent_id, key, value, confidence, source FROM beliefs WHERE session_id = $1",
      sid,
    );
  } catch {
    return [];
  }
  const beliefs: AgentBelief[] = beliefsFromDbRows(
    (rows as Record<string, unknown>[]) ?? [],
  );
  const divs = detectDivergences(beliefs);

  const out: LiveDivergenceResult[] = [];
  for (const d of divs) {
    const agents = Array.from(new Set(d.agents.map((b) => b.agent_id))).sort();
    const distinct = [...d.distinct_values];
    out.push(
      makeLiveDivergenceResult({
        key: d.key,
        distinct_values: distinct,
        agents_involved: agents,
        severity: d.severity,
        rationale: buildRationale({
          key: d.key,
          agents_involved: agents,
          distinct_values: distinct,
          severity: d.severity,
        }),
      }),
    );
  }
  return out;
}

/** Convenience: divergence detection for a single belief key. */
export async function divergencesForKey(
  sessionId: string,
  key: string,
): Promise<LiveDivergenceResult | null> {
  return detectLiveDivergence({
    sessionId,
    justEmittedKey: key,
  });
}
