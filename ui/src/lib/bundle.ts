// Bundle types — the static cooperative-build artifact format produced by
// runtime/modal/_payloads/public_benchmark_v32.py and committed to
// bench/results/v32_app_bundle/.

import { ORDERED_KEYS, ROLE_TITLE, VENDORS, vendorForAgentId } from "./vendors";

export interface BundleSummary {
  vendor_count: number;
  files_written: number;
  intents: number;
  app_runs: boolean;
  app_check: string;
  elapsed_s?: number;
}

export interface BundleRole {
  framework: string;      // e.g. "autogen"
  vendor: string;         // e.g. "Microsoft"
  role: string;           // e.g. "API Architect"
  file: string;           // e.g. "api_spec.md"
  bytes: number;
  via_fallback: boolean;  // true if direct framework capture was empty/invalid
  reason?: string;        // why fallback fired (or empty if direct)
}

export interface BundleEnvelope {
  type: string;
  id?: string;
  agent_id: string;
  vendor_key?: string;    // inferred from agent_id via vendors.ts
  vendor_name?: string;
  badge?: string;
  scope: string[];
  action: string | object;
  status?: string;
  ts_ms: number;
}

export interface Bundle {
  id: string;             // "v32"
  session: string;        // "v32_app_1778635046"
  commit: string;         // "6340949"
  produced_at: string;    // ISO timestamp
  summary: BundleSummary;
  roles: BundleRole[];
  envelopes: BundleEnvelope[];
  files: Record<string, string>;
}

// Per-role file map and fallback reasons captured from the v32 run.
// We hard-code these because the run log isn't part of the static bundle —
// only the produced files + envelopes.jsonl are. Source of truth is the
// stdout block we saved at bench/results/public_benchmark_20260512-211906.json.
export const V32_ROLE_META: Record<string, {
  file: string;
  via_fallback: boolean;
  reason?: string;
  bytes_direct?: number;
}> = {
  autogen:       { file: "api_spec.md",  via_fallback: false, bytes_direct: 177 },
  crewai:        { file: "main.py",      via_fallback: true,  reason: "validator: missing 'todos' + 'jsonify' markers (got 373B stub)" },
  langgraph:     { file: "test_app.py",  via_fallback: false, bytes_direct: 244 },
  hermes:        { file: "PLAN.md",      via_fallback: false, bytes_direct: 613 },
  smolagents:    { file: "models.py",    via_fallback: true,  reason: "CodeAgent dispatched tool with empty content arg" },
  agno:          { file: "README.md",    via_fallback: true,  reason: "tool dispatch with empty content arg" },
  llama_index:   { file: "LINT.md",      via_fallback: false, bytes_direct: 639 },
  pydantic_ai:   { file: "schemas.py",   via_fallback: false, bytes_direct: 111 },
  openai_agents: { file: "deploy.sh",    via_fallback: false, bytes_direct: 32 },
  google_adk:    { file: "REVIEW.md",    via_fallback: false, bytes_direct: 251 },
};

// Parse a single envelopes.jsonl line into a BundleEnvelope.
export function parseEnvelopeLine(line: string): BundleEnvelope | null {
  const t = line.trim();
  if (!t) return null;
  try {
    const j = JSON.parse(t) as {
      type: string;
      id?: string;
      agent_id: string;
      scope?: string[];
      action?: string | object;
      status?: string;
      ts_ms?: number;
    };
    const vendor = vendorForAgentId(j.agent_id);
    return {
      type: j.type,
      id: j.id,
      agent_id: j.agent_id,
      vendor_key: vendor?.key,
      vendor_name: vendor?.name,
      badge: vendor?.badge,
      scope: j.scope ?? [],
      action: j.action ?? "",
      status: j.status,
      ts_ms: j.ts_ms ?? 0,
    };
  } catch {
    return null;
  }
}

export function parseEnvelopesJsonl(text: string): BundleEnvelope[] {
  return text
    .split(/\r?\n/)
    .map(parseEnvelopeLine)
    .filter((e): e is BundleEnvelope => e !== null)
    .sort((a, b) => a.ts_ms - b.ts_ms);
}

export function buildRoles(files: Record<string, string>): BundleRole[] {
  return ORDERED_KEYS.map((k) => {
    const meta = V32_ROLE_META[k];
    const v = VENDORS[k];
    const content = files[meta.file] ?? "";
    return {
      framework: k,
      vendor: v.vendor,
      role: ROLE_TITLE[k],
      file: meta.file,
      bytes: content.length,
      via_fallback: meta.via_fallback,
      reason: meta.reason,
    };
  });
}
