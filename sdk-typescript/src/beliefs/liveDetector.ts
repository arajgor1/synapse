/**
 * Per-emission divergence detection.
 *
 * Ported from sdk-python/synapse/beliefs/live_detector.py.
 *
 * Re-runs the divergence detector against the state graph immediately
 * after a BELIEF is emitted. If divergence is found, returns a structured
 * result that intend() / framework adapters can act on.
 */
import {
  type AgentBelief,
  detectDivergences,
} from "./divergence.js";

export interface LiveDivergenceResult {
  key: string;
  distinct_values: unknown[];
  agents_involved: string[];
  severity: number;
  rationale: string;
  toJSON(): Record<string, unknown>;
}

/** Build a LiveDivergenceResult with a `toJSON` method preserved. */
export function makeLiveDivergenceResult(args: {
  key: string;
  distinct_values: unknown[];
  agents_involved: string[];
  severity: number;
  rationale: string;
}): LiveDivergenceResult {
  return {
    key: args.key,
    distinct_values: [...args.distinct_values],
    agents_involved: [...args.agents_involved],
    severity: args.severity,
    rationale: args.rationale,
    toJSON(): Record<string, unknown> {
      return {
        key: args.key,
        distinct_values: [...args.distinct_values],
        agents_involved: [...args.agents_involved],
        severity: args.severity,
        rationale: args.rationale,
      };
    },
  };
}

/**
 * Return a Python-repr-ish form of an array of values. Mirrors
 * `repr([...])` enough for rationale strings to be informative.
 */
function reprValues(values: unknown[]): string {
  const parts: string[] = [];
  for (const v of values) {
    if (typeof v === "string") {
      parts.push(`'${v.replace(/\\/g, "\\\\").replace(/'/g, "\\'")}'`);
    } else if (v === null) {
      parts.push("None");
    } else if (v === true) {
      parts.push("True");
    } else if (v === false) {
      parts.push("False");
    } else {
      try {
        parts.push(JSON.stringify(v));
      } catch {
        parts.push(String(v));
      }
    }
  }
  return `[${parts.join(", ")}]`;
}

export interface DetectLiveDivergenceArgs {
  sessionId: string;
  justEmittedKey: string;
  /**
   * Optional runtime override (mostly for tests). When omitted, we lazy-import
   * `getOrInitRuntime` from `../intend.js`.
   */
  runtime?: unknown;
}

interface RuntimeLike {
  state?: { pool?: { fetch?: (...args: unknown[]) => Promise<unknown[]> } } | null;
  get?: (key: string) => unknown;
}

function readState(rt: unknown): {
  pool: { fetch: (q: string, ...args: unknown[]) => Promise<unknown[]> };
} | null {
  if (rt === null || typeof rt !== "object") return null;
  const r = rt as RuntimeLike;
  let state: unknown;
  if (typeof r.get === "function") {
    state = r.get("state");
  } else {
    state = (r as Record<string, unknown>)["state"];
  }
  if (state === null || state === undefined || typeof state !== "object") {
    return null;
  }
  const pool = (state as Record<string, unknown>)["pool"];
  if (pool === null || pool === undefined || typeof pool !== "object") {
    return null;
  }
  const fetchFn = (pool as Record<string, unknown>)["fetch"];
  if (typeof fetchFn !== "function") return null;
  return {
    pool: {
      fetch: fetchFn as (q: string, ...args: unknown[]) => Promise<unknown[]>,
    },
  };
}

/**
 * Pull all beliefs for `sessionId` matching `justEmittedKey` from the state
 * graph, run divergence detection on them. Returns null if no state graph
 * is configured, no divergence found, or only one agent has emitted.
 */
export async function detectLiveDivergence(
  args: DetectLiveDivergenceArgs,
): Promise<LiveDivergenceResult | null> {
  let rt = args.runtime;
  if (rt === undefined) {
    try {
      const mod = (await import("../intend.js")) as Record<string, unknown>;
      const fn =
        (mod["_getOrInitRuntime"] as (() => unknown) | undefined) ??
        (mod["getOrInitRuntime"] as (() => unknown) | undefined);
      rt = fn ? fn() : null;
    } catch {
      rt = null;
    }
  }
  const state = readState(rt);
  if (state === null) return null;

  const rows = (await state.pool.fetch(
    `
    SELECT agent_id, key, value, confidence, source
    FROM beliefs
    WHERE session_id = $1 AND key = $2
    `,
    args.sessionId,
    args.justEmittedKey,
  )) as Record<string, unknown>[];

  if (!rows || rows.length < 2) return null;

  const beliefs: AgentBelief[] = rows.map((r) => ({
    agent_id: String(r["agent_id"]),
    key: String(r["key"]),
    value: r["value"],
    confidence: Number(r["confidence"]),
    source: String(r["source"]),
  }));

  const divs = detectDivergences(beliefs);
  if (divs.length === 0) return null;

  const d = divs[0];
  if (!d) return null;
  const distinct = [...d.distinct_values];
  const agents = Array.from(new Set(d.agents.map((b) => b.agent_id))).sort();
  const rationale =
    `BELIEF divergence on '${d.key}': ${agents.length} agent(s) ` +
    `(${agents.join(", ")}) hold ${distinct.length} distinct value(s): ` +
    `${reprValues(distinct)}. Severity=${d.severity.toFixed(2)}.`;

  return makeLiveDivergenceResult({
    key: d.key,
    distinct_values: distinct,
    agents_involved: agents,
    severity: d.severity,
    rationale,
  });
}

/** Internal helper exported for `api.ts` so it shares rationale shape. */
export function buildRationale(args: {
  key: string;
  agents_involved: string[];
  distinct_values: unknown[];
  severity: number;
}): string {
  return (
    `BELIEF divergence on '${args.key}': ${args.agents_involved.length} agent(s) ` +
    `(${args.agents_involved.join(", ")}) hold ${args.distinct_values.length} ` +
    `distinct value(s): ${reprValues(args.distinct_values)}. ` +
    `Severity=${args.severity.toFixed(2)}.`
  );
}
