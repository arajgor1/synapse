/**
 * Belief divergence detection — pure-function module.
 *
 * Ported from sdk-python/synapse/beliefs/divergence.py. No I/O, fully
 * testable. When multiple agents assert different values for the same
 * belief key, the divergence detector flags it.
 */

export type BeliefSource = "observed" | "inferred" | "assumed" | string;

export interface AgentBelief {
  agent_id: string;
  key: string;
  value: unknown;
  confidence: number;
  /** "observed" | "inferred" | "assumed" */
  source: BeliefSource;
}

export interface BeliefDivergence {
  key: string;
  agents: AgentBelief[];
  severity: number;
  /** Distinct values held across the agents (insertion order). */
  distinct_values: unknown[];
}

/** Numeric weight derived from `source` × `confidence`. */
export function evidentialWeight(b: AgentBelief): number {
  const rankMap: Record<string, number> = {
    observed: 1.0,
    inferred: 0.7,
    assumed: 0.4,
  };
  const rank = rankMap[b.source] ?? 0.5;
  const w = b.confidence * rank;
  if (Number.isNaN(w)) return 0.0;
  return Math.min(1.0, Math.max(0.0, w));
}

/** Float-fuzz comparison mirroring Python's _values_equal. */
export function valuesEqual(a: unknown, b: unknown): boolean {
  if (
    typeof a === "number" &&
    typeof b === "number" &&
    !Number.isInteger(a) &&
    !Number.isInteger(b)
  ) {
    return Math.abs(a - b) < 1e-9;
  }
  // Mirror Python equality for floats vs ints — if either is float-typed by
  // having a fractional part, use fuzz; otherwise structural equality.
  if (typeof a === "number" && typeof b === "number") {
    return Math.abs(a - b) < 1e-9;
  }
  // Structural deep-equal for arrays/objects, primitive equality for scalars.
  if (a === b) return true;
  if (a === null || b === null) return false;
  if (typeof a !== typeof b) return false;
  if (typeof a === "object") {
    try {
      return JSON.stringify(a) === JSON.stringify(b);
    } catch {
      return false;
    }
  }
  return false;
}

/** Compute distinct values within a group, preserving insertion order. */
function distinctIn(group: AgentBelief[]): unknown[] {
  const distinct: unknown[] = [];
  for (const b of group) {
    if (!distinct.some((d) => valuesEqual(b.value, d))) {
      distinct.push(b.value);
    }
  }
  return distinct;
}

/**
 * Group beliefs by key; emit a BeliefDivergence whenever ≥2 agents disagree
 * on the same key. Returned list is sorted severity-descending.
 */
export function detectDivergences(
  beliefs: Iterable<AgentBelief>,
): BeliefDivergence[] {
  const byKey = new Map<string, AgentBelief[]>();
  for (const b of beliefs) {
    let arr = byKey.get(b.key);
    if (!arr) {
      arr = [];
      byKey.set(b.key, arr);
    }
    arr.push(b);
  }

  const out: BeliefDivergence[] = [];
  for (const [key, group] of byKey) {
    if (group.length < 2) continue;
    const distinct = distinctIn(group);
    if (distinct.length < 2) continue;
    const avgWeight =
      group.reduce((s, b) => s + evidentialWeight(b), 0) / group.length;
    const scale = Math.min(1.0, distinct.length / 3.0);
    const severity = Math.min(1.0, avgWeight * (0.5 + 0.5 * scale));
    out.push({
      key,
      agents: [...group],
      severity,
      distinct_values: distinct,
    });
  }

  out.sort((a, b) => b.severity - a.severity);
  return out;
}

/** Build AgentBelief[] from generic DB-row dicts. */
export function beliefsFromDbRows(
  rows: Iterable<Record<string, unknown>>,
): AgentBelief[] {
  const out: AgentBelief[] = [];
  for (const r of rows) {
    out.push({
      agent_id: String(r["agent_id"]),
      key: String(r["key"]),
      value: r["value"],
      confidence: Number(r["confidence"]),
      source: String(r["source"]),
    });
  }
  return out;
}
