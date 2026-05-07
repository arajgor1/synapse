/**
 * Vitest unit tests for the beliefs module — mock-only, no DB / LLM calls.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  type AgentBelief,
  beliefsFromDbRows,
  detectDivergences,
  evidentialWeight,
  valuesEqual,
} from "./divergence.js";
import {
  extractBeliefsWithLLM,
  parseExtraction,
} from "./extractor.js";
import {
  detectLiveDivergence,
  makeLiveDivergenceResult,
} from "./liveDetector.js";
import { divergencesForKey, emitBelief, listDivergences } from "./api.js";

// Mock ../intend.js — A4 owns it; we don't import the real module.
vi.mock("../intend.js", () => ({
  _getOrInitRuntime: () => null,
  _getAgent: async () => null,
  getOrInitRuntime: () => null,
  getAgent: async () => null,
}));

// Mock ../llm/config.js for extractBeliefsWithLLM no-LLM tests.
vi.mock("../llm/config.js", () => ({
  getInternalLlm: () => null,
}));

// ---------------------------------------------------------------------------
// divergence.ts
// ---------------------------------------------------------------------------

describe("evidentialWeight", () => {
  it("ranks observed > inferred > assumed", () => {
    const obs: AgentBelief = { agent_id: "a", key: "k", value: 1, confidence: 1, source: "observed" };
    const inf: AgentBelief = { ...obs, source: "inferred" };
    const ass: AgentBelief = { ...obs, source: "assumed" };
    expect(evidentialWeight(obs)).toBeCloseTo(1.0);
    expect(evidentialWeight(inf)).toBeCloseTo(0.7);
    expect(evidentialWeight(ass)).toBeCloseTo(0.4);
  });

  it("clamps confidence × rank to [0,1]", () => {
    const b: AgentBelief = { agent_id: "a", key: "k", value: 1, confidence: 5, source: "observed" };
    expect(evidentialWeight(b)).toBe(1.0);
    const neg: AgentBelief = { ...b, confidence: -1 };
    expect(evidentialWeight(neg)).toBe(0.0);
  });
});

describe("valuesEqual (float fuzz)", () => {
  it("treats near-equal floats as equal", () => {
    expect(valuesEqual(1.0000000001, 1.0)).toBe(true);
  });
  it("treats clearly different floats as unequal", () => {
    expect(valuesEqual(1.0, 1.5)).toBe(false);
  });
  it("structurally compares strings/objects", () => {
    expect(valuesEqual("a", "a")).toBe(true);
    expect(valuesEqual({ a: 1 }, { a: 1 })).toBe(true);
    expect(valuesEqual({ a: 1 }, { a: 2 })).toBe(false);
  });
});

describe("detectDivergences", () => {
  it("returns nothing for a single belief", () => {
    const b: AgentBelief = { agent_id: "a", key: "k", value: 1, confidence: 1, source: "observed" };
    expect(detectDivergences([b])).toEqual([]);
  });

  it("returns nothing when all agents agree", () => {
    const a: AgentBelief = { agent_id: "a", key: "k", value: "x", confidence: 1, source: "observed" };
    const b: AgentBelief = { agent_id: "b", key: "k", value: "x", confidence: 1, source: "observed" };
    expect(detectDivergences([a, b])).toEqual([]);
  });

  it("flags disagreement and computes severity", () => {
    const a: AgentBelief = { agent_id: "a", key: "k", value: "x", confidence: 1, source: "observed" };
    const b: AgentBelief = { agent_id: "b", key: "k", value: "y", confidence: 1, source: "observed" };
    const divs = detectDivergences([a, b]);
    expect(divs).toHaveLength(1);
    const first = divs[0]!;
    expect(first.key).toBe("k");
    expect(first.distinct_values).toEqual(["x", "y"]);
    // 2 distinct / 3 = 0.667; scale = 0.667; severity = 1.0 * (0.5 + 0.5*0.667) = 0.833
    expect(first.severity).toBeCloseTo(1.0 * (0.5 + 0.5 * (2 / 3)), 5);
  });

  it("sorts results by severity descending", () => {
    // High-severity divergence: 3 distinct values, observed
    const k1 = ["a", "b", "c"].map((id, i): AgentBelief => ({
      agent_id: id, key: "high", value: i, confidence: 1, source: "observed",
    }));
    // Low-severity: 2 distinct values, assumed (rank 0.4)
    const k2: AgentBelief[] = [
      { agent_id: "x", key: "low", value: 1, confidence: 1, source: "assumed" },
      { agent_id: "y", key: "low", value: 2, confidence: 1, source: "assumed" },
    ];
    const divs = detectDivergences([...k2, ...k1]);
    expect(divs).toHaveLength(2);
    expect(divs[0]!.key).toBe("high");
    expect(divs[1]!.key).toBe("low");
    expect(divs[0]!.severity).toBeGreaterThan(divs[1]!.severity);
  });

  it("ignores keys with only one agent emission", () => {
    const a: AgentBelief = { agent_id: "a", key: "lonely", value: 1, confidence: 1, source: "observed" };
    const b: AgentBelief = { agent_id: "b", key: "shared", value: "x", confidence: 1, source: "observed" };
    const c: AgentBelief = { agent_id: "c", key: "shared", value: "y", confidence: 1, source: "observed" };
    const divs = detectDivergences([a, b, c]);
    expect(divs).toHaveLength(1);
    expect(divs[0]!.key).toBe("shared");
  });
});

describe("beliefsFromDbRows", () => {
  it("coerces numeric fields and string fields", () => {
    const rows = [
      { agent_id: "a", key: "k", value: { x: 1 }, confidence: "0.9", source: "observed" },
    ];
    const out = beliefsFromDbRows(rows);
    expect(out[0]!.confidence).toBeCloseTo(0.9);
    expect(out[0]!.value).toEqual({ x: 1 });
  });
});

// ---------------------------------------------------------------------------
// extractor.ts
// ---------------------------------------------------------------------------

describe("parseExtraction", () => {
  it("parses a clean JSON list", () => {
    const out = parseExtraction(
      '[{"key": "k", "value": "v", "confidence": 0.9, "evidence": "e"}]',
    );
    expect(out).toHaveLength(1);
    expect(out[0]!.key).toBe("k");
    expect(out[0]!.value).toBe("v");
    expect(out[0]!.confidence).toBe(0.9);
    expect(out[0]!.evidence).toBe("e");
  });

  it("strips ```json``` code fences", () => {
    const text = '```json\n[{"key": "k", "value": 1}]\n```';
    const out = parseExtraction(text);
    expect(out).toHaveLength(1);
    expect(out[0]!.value).toBe(1);
  });

  it("strips bare ``` code fences", () => {
    const text = '```\n[{"key": "k", "value": 1}]\n```';
    const out = parseExtraction(text);
    expect(out).toHaveLength(1);
  });

  it("tolerates a preamble before the JSON list", () => {
    const text = 'Here are the facts: [{"key": "k", "value": 1}]';
    const out = parseExtraction(text);
    expect(out).toHaveLength(1);
    expect(out[0]!.key).toBe("k");
  });

  it("drops malformed entries (missing key/value)", () => {
    const text = '[{"key": "ok", "value": 1}, {"value": "no key"}, "scalar"]';
    const out = parseExtraction(text);
    expect(out).toHaveLength(1);
    expect(out[0]!.key).toBe("ok");
  });

  it("caps the result list at 3 facts", () => {
    const items = Array.from({ length: 5 }, (_, i) => ({
      key: `k${i}`,
      value: i,
    }));
    const out = parseExtraction(JSON.stringify(items));
    expect(out).toHaveLength(3);
  });

  it("returns [] on empty/garbage input", () => {
    expect(parseExtraction("")).toEqual([]);
    expect(parseExtraction("not json")).toEqual([]);
    expect(parseExtraction("{}")).toEqual([]);
    expect(parseExtraction("[unparseable")).toEqual([]);
  });

  it("clamps confidence to [0,1] and defaults when missing/invalid", () => {
    const out = parseExtraction(
      '[{"key": "a", "value": 1, "confidence": 5},' +
        '{"key": "b", "value": 1, "confidence": -1},' +
        '{"key": "c", "value": 1}]',
    );
    expect(out[0]!.confidence).toBe(1.0);
    expect(out[1]!.confidence).toBe(0.0);
    expect(out[2]!.confidence).toBe(0.85);
  });
});

describe("extractBeliefsWithLLM", () => {
  it("returns [] when no LLM is configured (llm: null)", async () => {
    const out = await extractBeliefsWithLLM({
      toolName: "t",
      toolArgs: {},
      output: "anything",
      llm: null,
    });
    expect(out).toEqual([]);
  });

  it("returns [] when output is blank", async () => {
    const fakeLlm = { generate: vi.fn() };
    const out = await extractBeliefsWithLLM({
      toolName: "t",
      toolArgs: {},
      output: "   ",
      llm: fakeLlm,
    });
    expect(out).toEqual([]);
    expect(fakeLlm.generate).not.toHaveBeenCalled();
  });

  it("returns [] when LLM returns garbage", async () => {
    const fakeLlm = {
      generate: vi.fn().mockResolvedValue("not even close to JSON"),
    };
    const out = await extractBeliefsWithLLM({
      toolName: "t",
      toolArgs: {},
      output: "some real output text",
      llm: fakeLlm,
    });
    expect(out).toEqual([]);
    expect(fakeLlm.generate).toHaveBeenCalledOnce();
  });

  it("parses a valid LLM response via the bridge .generate() path", async () => {
    const fakeLlm = {
      generate: vi
        .fn()
        .mockResolvedValue('[{"key": "primary_key", "value": "user_id", "confidence": 0.95}]'),
    };
    const out = await extractBeliefsWithLLM({
      toolName: "sql_run",
      toolArgs: { q: "select 1" },
      output: "PRIMARY KEY (user_id)",
      llm: fakeLlm,
    });
    expect(out).toHaveLength(1);
    expect(out[0]!.key).toBe("primary_key");
    expect(out[0]!.value).toBe("user_id");
    expect(out[0]!.confidence).toBeCloseTo(0.95);
  });

  it("falls back to Anthropic-shaped client when generate is missing", async () => {
    const create = vi.fn().mockResolvedValue({
      content: [{ text: '[{"key": "k", "value": 1}]' }],
    });
    const fakeLlm = { _client: { messages: { create } } };
    const out = await extractBeliefsWithLLM({
      toolName: "t",
      toolArgs: {},
      output: "real output",
      llm: fakeLlm,
    });
    expect(out).toHaveLength(1);
    expect(create).toHaveBeenCalledOnce();
  });

  it("falls back to OpenAI-shaped client when others are missing", async () => {
    const create = vi.fn().mockResolvedValue({
      choices: [{ message: { content: '[{"key": "k", "value": "v"}]' } }],
    });
    const fakeLlm = { _client: { chat: { completions: { create } } } };
    const out = await extractBeliefsWithLLM({
      toolName: "t",
      toolArgs: {},
      output: "real output",
      llm: fakeLlm,
    });
    expect(out).toHaveLength(1);
    expect(create).toHaveBeenCalledOnce();
  });
});

// ---------------------------------------------------------------------------
// liveDetector.ts
// ---------------------------------------------------------------------------

describe("detectLiveDivergence", () => {
  it("returns null when no runtime/state is configured", async () => {
    const out = await detectLiveDivergence({
      sessionId: "s",
      justEmittedKey: "k",
    });
    expect(out).toBeNull();
  });

  it("returns null when only one row is present (single agent)", async () => {
    const fetchFn = vi.fn().mockResolvedValue([
      { agent_id: "a", key: "k", value: "x", confidence: 1, source: "observed" },
    ]);
    const runtime = { state: { pool: { fetch: fetchFn } } };
    const out = await detectLiveDivergence({
      sessionId: "s",
      justEmittedKey: "k",
      runtime,
    });
    expect(out).toBeNull();
  });

  it("returns null when agents agree", async () => {
    const fetchFn = vi.fn().mockResolvedValue([
      { agent_id: "a", key: "k", value: "x", confidence: 1, source: "observed" },
      { agent_id: "b", key: "k", value: "x", confidence: 1, source: "observed" },
    ]);
    const runtime = { state: { pool: { fetch: fetchFn } } };
    const out = await detectLiveDivergence({
      sessionId: "s",
      justEmittedKey: "k",
      runtime,
    });
    expect(out).toBeNull();
  });

  it("returns a LiveDivergenceResult on disagreement", async () => {
    const fetchFn = vi.fn().mockResolvedValue([
      { agent_id: "alice", key: "fmt", value: "csv", confidence: 1, source: "observed" },
      { agent_id: "bob", key: "fmt", value: "json", confidence: 1, source: "observed" },
    ]);
    const runtime = { state: { pool: { fetch: fetchFn } } };
    const out = await detectLiveDivergence({
      sessionId: "s",
      justEmittedKey: "fmt",
      runtime,
    });
    expect(out).not.toBeNull();
    expect(out!.key).toBe("fmt");
    expect(out!.distinct_values).toEqual(["csv", "json"]);
    expect(out!.agents_involved).toEqual(["alice", "bob"]);
    expect(out!.severity).toBeGreaterThan(0);
    expect(out!.rationale).toContain("fmt");
  });

  it("returns null when state graph fetch returns []", async () => {
    const fetchFn = vi.fn().mockResolvedValue([]);
    const runtime = { state: { pool: { fetch: fetchFn } } };
    const out = await detectLiveDivergence({
      sessionId: "s",
      justEmittedKey: "k",
      runtime,
    });
    expect(out).toBeNull();
  });
});

describe("LiveDivergenceResult.toJSON", () => {
  it("round-trips via toJSON()", () => {
    const r = makeLiveDivergenceResult({
      key: "k",
      distinct_values: ["a", "b"],
      agents_involved: ["x", "y"],
      severity: 0.75,
      rationale: "because",
    });
    const j = r.toJSON();
    expect(j).toEqual({
      key: "k",
      distinct_values: ["a", "b"],
      agents_involved: ["x", "y"],
      severity: 0.75,
      rationale: "because",
    });
    // Also serialize via JSON.stringify for safety.
    const s = JSON.parse(JSON.stringify(r));
    expect(s.key).toBe("k");
    expect(s.severity).toBe(0.75);
  });
});

// ---------------------------------------------------------------------------
// api.ts (offline-mode behavior — no real runtime)
// ---------------------------------------------------------------------------

describe("emitBelief (offline)", () => {
  beforeEach(() => {
    delete process.env["SYNAPSE_SESSION_ID"];
  });
  afterEach(() => {
    delete process.env["SYNAPSE_SESSION_ID"];
  });

  it("returns null when no agent runtime is available", async () => {
    const out = await emitBelief({
      agent: "alice",
      key: "k",
      value: 1,
    });
    expect(out).toBeNull();
  });
});

describe("listDivergences (offline)", () => {
  it("returns [] when no runtime is configured", async () => {
    const out = await listDivergences("some-session");
    expect(out).toEqual([]);
  });

  it("returns [] when no session id is provided or in env", async () => {
    delete process.env["SYNAPSE_SESSION_ID"];
    const out = await listDivergences();
    expect(out).toEqual([]);
  });
});

describe("divergencesForKey (offline)", () => {
  it("returns null when no runtime is configured", async () => {
    const out = await divergencesForKey("s", "k");
    expect(out).toBeNull();
  });
});
