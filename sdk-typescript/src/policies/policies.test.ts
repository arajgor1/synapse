/**
 * Unit tests for the policies module.
 *
 * Mocks `../llm/config` and `../intend` because A1/A4 agents own those
 * modules and they may not yet exist when this module is compiled and
 * tested in isolation. Each AutoMergePolicy test sets up the relevant
 * mock surface explicitly.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  MergePolicy,
  MergeDecision,
  SynapseConflict,
  RedirectPolicy,
  WaitPolicy,
  AbortPolicy,
  AutoMergePolicy,
  NoOpPolicy,
  resolvePolicy,
  criticalScopeMatch,
  normalizeCriticalScopes,
  type IntentionHandleLike,
} from "./index.js";
import type { Conflict } from "../types.js";

// Importing registry.ts has the side effect of wiring MergePolicy.redirect etc.
// The index.ts re-exports already pulled it in.

// ---------------------------------------------------------------------------
// Mocks for ../llm/config and ../intend (owned by other agents).
// We define mutable state so individual tests can override behavior.
// ---------------------------------------------------------------------------
const llmState: { llm: unknown } = { llm: null };
const intendState: { rt: unknown } = { rt: null };

vi.mock("../llm/config.js", () => ({
  getInternalLlm: () => llmState.llm,
}));

vi.mock("../intend.js", () => ({
  getOrInitRuntime: () => intendState.rt,
}));

beforeEach(() => {
  llmState.llm = null;
  intendState.rt = null;
});

// ---------------------------------------------------------------------------
// Test fixtures
// ---------------------------------------------------------------------------
function makeHandle(overrides: Partial<IntentionHandleLike> = {}): IntentionHandleLike {
  return {
    scope: ["repo.fs.foo.py:w"],
    agentId: "agent_a",
    sessionId: "sess_1",
    intentionId: "int_1",
    ...overrides,
  };
}

function makeConflict(overrides: Partial<Conflict> = {}): Conflict {
  return {
    intention_id: "int_1",
    conflicting_intentions: [
      {
        intention_id: "int_other",
        agent_id: "agent_b",
        scope: ["repo.fs.foo.py:w"],
      },
    ],
    kind: "scope_overlap",
    suggested_resolution: "pivot",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// criticalScopeMatch / normalizeCriticalScopes
// ---------------------------------------------------------------------------
describe("normalizeCriticalScopes", () => {
  it("returns empty array for null/undefined/empty", () => {
    expect(normalizeCriticalScopes(null)).toEqual([]);
    expect(normalizeCriticalScopes(undefined)).toEqual([]);
    expect(normalizeCriticalScopes([])).toEqual([]);
  });

  it("strips whitespace and drops empty strings", () => {
    expect(normalizeCriticalScopes(["  billing.* ", "", "  ", "prod.deploy.*"])).toEqual([
      "billing.*",
      "prod.deploy.*",
    ]);
  });

  it("handles iterables", () => {
    const set = new Set(["a", "b"]);
    const result = normalizeCriticalScopes(set);
    expect(result.sort()).toEqual(["a", "b"]);
  });
});

describe("criticalScopeMatch", () => {
  it("matches exact scope", () => {
    expect(criticalScopeMatch(["billing.charge"], ["billing.charge"])).toBe("billing.charge");
  });

  it("matches glob pattern", () => {
    expect(criticalScopeMatch(["billing.charge"], ["billing.*"])).toBe("billing.*");
    expect(criticalScopeMatch(["prod.deploy.api"], ["prod.deploy.*"])).toBe("prod.deploy.*");
  });

  it("returns null when no pattern matches", () => {
    expect(criticalScopeMatch(["repo.fs.user.py"], ["billing.*"])).toBeNull();
    expect(criticalScopeMatch([], ["billing.*"])).toBeNull();
    expect(criticalScopeMatch(["billing.charge"], [])).toBeNull();
  });

  it("strips :w / :r modifier before matching", () => {
    expect(criticalScopeMatch(["billing.charge:w"], ["billing.*"])).toBe("billing.*");
    expect(criticalScopeMatch(["billing.charge:r"], ["billing.*"])).toBe("billing.*");
  });

  it("strips modifier from pattern too", () => {
    expect(criticalScopeMatch(["billing.charge:w"], ["billing.*:w"])).toBe("billing.*:w");
  });

  it("returns the FIRST matched pattern", () => {
    const result = criticalScopeMatch(
      ["billing.charge"],
      ["nope.*", "billing.*", "billing.charge"],
    );
    expect(result).toBe("billing.*");
  });

  it("supports ? single-char glob", () => {
    expect(criticalScopeMatch(["abc"], ["a?c"])).toBe("a?c");
    expect(criticalScopeMatch(["abcd"], ["a?c"])).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// resolvePolicy
// ---------------------------------------------------------------------------
describe("resolvePolicy", () => {
  it("returns null for null/undefined", () => {
    expect(resolvePolicy(null)).toBeNull();
    expect(resolvePolicy(undefined)).toBeNull();
  });

  it("returns instance unchanged", () => {
    const p = new RedirectPolicy();
    expect(resolvePolicy(p)).toBe(p);
  });

  it("resolves canonical names", () => {
    expect(resolvePolicy("redirect")?.name).toBe("redirect");
    expect(resolvePolicy("wait")?.name).toBe("wait");
    expect(resolvePolicy("abort")?.name).toBe("abort");
    expect(resolvePolicy("auto_merge")?.name).toBe("auto_merge");
    expect(resolvePolicy("no_op")?.name).toBe("no_op");
  });

  it("resolves aliases", () => {
    expect(resolvePolicy("automerge")?.name).toBe("auto_merge");
    expect(resolvePolicy("merge")?.name).toBe("auto_merge");
    expect(resolvePolicy("noop")?.name).toBe("no_op");
    expect(resolvePolicy("auto-merge")?.name).toBe("auto_merge");
    expect(resolvePolicy("NO_OP")?.name).toBe("no_op");
  });

  it("returns null for unknown name", () => {
    expect(resolvePolicy("bogus_policy")).toBeNull();
  });

  it("throws TypeError for unsupported types", () => {
    expect(() => resolvePolicy(42 as unknown as null)).toThrow(TypeError);
  });
});

// ---------------------------------------------------------------------------
// MergePolicy.redirect / .wait / .abort / .autoMerge / .noOp singletons
// ---------------------------------------------------------------------------
describe("MergePolicy class-level singletons", () => {
  it("MergePolicy.redirect is a RedirectPolicy", () => {
    expect(MergePolicy.redirect).toBeInstanceOf(RedirectPolicy);
    expect(MergePolicy.redirect.name).toBe("redirect");
  });

  it("MergePolicy.wait is a WaitPolicy", () => {
    expect(MergePolicy.wait).toBeInstanceOf(WaitPolicy);
  });

  it("MergePolicy.abort is an AbortPolicy", () => {
    expect(MergePolicy.abort).toBeInstanceOf(AbortPolicy);
  });

  it("MergePolicy.autoMerge is an AutoMergePolicy", () => {
    expect(MergePolicy.autoMerge).toBeInstanceOf(AutoMergePolicy);
  });

  it("MergePolicy.noOp is a NoOpPolicy", () => {
    expect(MergePolicy.noOp).toBeInstanceOf(NoOpPolicy);
  });

  it("singletons are stable references", () => {
    expect(resolvePolicy("redirect")).toBe(MergePolicy.redirect);
    expect(resolvePolicy("auto_merge")).toBe(MergePolicy.autoMerge);
  });
});

// ---------------------------------------------------------------------------
// Built-in resolve() behavior
// ---------------------------------------------------------------------------
describe("NoOpPolicy", () => {
  it("returns PROCEED", async () => {
    const p = new NoOpPolicy();
    const action = await p.resolve(makeHandle(), [makeConflict()]);
    expect(action.decision).toBe(MergeDecision.PROCEED);
    expect(action.rationale).toMatch(/no_op/);
  });
});

describe("AbortPolicy", () => {
  it("returns ABORT with rationale", async () => {
    const p = new AbortPolicy();
    const action = await p.resolve(makeHandle(), [makeConflict()]);
    expect(action.decision).toBe(MergeDecision.ABORT);
    expect(action.rationale).toMatch(/Aborted/);
  });
});

describe("WaitPolicy", () => {
  it("returns WAIT with default timeout", async () => {
    const p = new WaitPolicy();
    const action = await p.resolve(makeHandle(), [makeConflict()]);
    expect(action.decision).toBe(MergeDecision.WAIT);
    expect(action.waitTimeoutMs).toBe(5000);
  });

  it("respects custom timeout", async () => {
    const p = new WaitPolicy(12000);
    const action = await p.resolve(makeHandle(), [makeConflict()]);
    expect(action.waitTimeoutMs).toBe(12000);
  });
});

describe("RedirectPolicy", () => {
  it("returns PROCEED with rationale citing other agents", async () => {
    const p = new RedirectPolicy();
    const action = await p.resolve(makeHandle(), [makeConflict()]);
    expect(action.decision).toBe(MergeDecision.PROCEED);
    expect(action.rationale).toContain("agent_b");
    expect(action.rationale).toContain("pivot");
  });

  it("falls back to placeholder when no conflicting agents available", async () => {
    const p = new RedirectPolicy();
    const conflict = makeConflict({ conflicting_intentions: [] });
    const action = await p.resolve(makeHandle(), [conflict]);
    expect(action.rationale).toContain("other agent(s)");
  });

  it("dedupes and sorts agent ids", async () => {
    const p = new RedirectPolicy();
    const c1 = makeConflict({
      conflicting_intentions: [
        { intention_id: "i1", agent_id: "zeta", scope: ["s"] },
        { intention_id: "i2", agent_id: "alpha", scope: ["s"] },
      ],
    });
    const c2 = makeConflict({
      conflicting_intentions: [{ intention_id: "i3", agent_id: "alpha", scope: ["s"] }],
    });
    const action = await p.resolve(makeHandle(), [c1, c2]);
    // alpha should appear before zeta
    expect(action.rationale.indexOf("alpha")).toBeLessThan(action.rationale.indexOf("zeta"));
  });
});

// ---------------------------------------------------------------------------
// SynapseConflict
// ---------------------------------------------------------------------------
describe("SynapseConflict", () => {
  it("is an Error subclass", () => {
    const e = new SynapseConflict([makeConflict()], ["scope.a"], "boom");
    expect(e).toBeInstanceOf(Error);
    expect(e).toBeInstanceOf(SynapseConflict);
    expect(e.message).toBe("boom");
    expect(e.scopes).toEqual(["scope.a"]);
    expect(e.conflicts).toHaveLength(1);
  });

  it("synthesizes message when rationale is empty", () => {
    const e = new SynapseConflict([makeConflict(), makeConflict()], ["s.a"]);
    expect(e.message).toContain("CONFLICT");
    expect(e.message).toContain("2 other agent(s)");
  });
});

// ---------------------------------------------------------------------------
// AutoMergePolicy fallback paths
// ---------------------------------------------------------------------------
describe("AutoMergePolicy", () => {
  it("falls back to PROCEED when no LLM is configured", async () => {
    llmState.llm = null;
    const p = new AutoMergePolicy();
    const action = await p.resolve(makeHandle(), [makeConflict()], {
      content: "draft",
    });
    expect(action.decision).toBe(MergeDecision.PROCEED);
    expect(action.rationale).toMatch(/no LLM|skipped/i);
  });

  it("falls back to PROCEED when proposed_action is missing", async () => {
    llmState.llm = { generate: async () => "merged" };
    const p = new AutoMergePolicy();
    const action = await p.resolve(makeHandle(), [makeConflict()]);
    expect(action.decision).toBe(MergeDecision.PROCEED);
    expect(action.rationale).toMatch(/proposedAction/);
  });

  it("falls back to PROCEED when proposed_action lacks the content key", async () => {
    llmState.llm = { generate: async () => "merged" };
    const p = new AutoMergePolicy();
    const action = await p.resolve(makeHandle(), [makeConflict()], { other: "x" });
    expect(action.decision).toBe(MergeDecision.PROCEED);
  });

  it("falls back to PROCEED when no priors are available (no runtime)", async () => {
    llmState.llm = { generate: async () => "merged" };
    intendState.rt = null;
    const p = new AutoMergePolicy();
    const action = await p.resolve(makeHandle(), [makeConflict()], {
      content: "draft",
    });
    expect(action.decision).toBe(MergeDecision.PROCEED);
    expect(action.rationale).toMatch(/couldn't fetch|state graph/);
  });

  it("falls back to PROCEED when LLM returns empty merge", async () => {
    llmState.llm = { generate: async () => "   " };
    intendState.rt = {
      bus: {
        redis: {
          xrange: async () => [
            [
              "1-0",
              {
                e: JSON.stringify({
                  type: "RESOLUTION",
                  payload: {
                    intention_id: "int_other",
                    state_diff: { content: "prior content" },
                  },
                }),
              },
            ],
          ],
        },
      },
    };
    const p = new AutoMergePolicy();
    const action = await p.resolve(makeHandle(), [makeConflict()], {
      content: "draft",
    });
    expect(action.decision).toBe(MergeDecision.PROCEED);
    expect(action.rationale).toMatch(/empty merge/);
  });

  it("returns MERGED when LLM merges successfully", async () => {
    llmState.llm = {
      generate: async () => "merged content",
    };
    intendState.rt = {
      bus: {
        redis: {
          xrange: async () => [
            [
              "1-0",
              {
                e: JSON.stringify({
                  type: "RESOLUTION",
                  payload: {
                    intention_id: "int_other",
                    state_diff: { content: "prior content" },
                  },
                }),
              },
            ],
          ],
        },
      },
    };
    const p = new AutoMergePolicy();
    const action = await p.resolve(makeHandle(), [makeConflict()], {
      content: "draft",
      path: "user.py",
    });
    expect(action.decision).toBe(MergeDecision.MERGED);
    expect(action.mergedAction).toEqual({
      content: "merged content",
      path: "user.py",
    });
    expect(action.rationale).toMatch(/Auto-merged/);
  });

  it("falls through to anthropic client when generate is missing", async () => {
    llmState.llm = {
      _model: "test-model",
      _client: {
        messages: {
          create: async () => ({ content: [{ text: "anthropic merged" }] }),
        },
      },
    };
    intendState.rt = {
      bus: {
        redis: {
          xrange: async () => [
            [
              "1-0",
              {
                e: JSON.stringify({
                  type: "RESOLUTION",
                  payload: {
                    intention_id: "int_other",
                    state_diff: { content: "prior" },
                  },
                }),
              },
            ],
          ],
        },
      },
    };
    const p = new AutoMergePolicy();
    const action = await p.resolve(makeHandle(), [makeConflict()], {
      content: "draft",
    });
    expect(action.decision).toBe(MergeDecision.MERGED);
    expect(action.mergedAction?.["content"]).toBe("anthropic merged");
  });

  it("falls through to openai client when generate and anthropic both missing", async () => {
    llmState.llm = {
      _model: "gpt-4o",
      _client: {
        chat: {
          completions: {
            create: async () => ({
              choices: [{ message: { content: "openai merged" } }],
            }),
          },
        },
      },
    };
    intendState.rt = {
      bus: {
        redis: {
          xrange: async () => [
            [
              "1-0",
              {
                e: JSON.stringify({
                  type: "RESOLUTION",
                  payload: {
                    intention_id: "int_other",
                    state_diff: { content: "prior" },
                  },
                }),
              },
            ],
          ],
        },
      },
    };
    const p = new AutoMergePolicy();
    const action = await p.resolve(makeHandle(), [makeConflict()], {
      content: "draft",
    });
    expect(action.decision).toBe(MergeDecision.MERGED);
    expect(action.mergedAction?.["content"]).toBe("openai merged");
  });

  it("uses content_key alias keys (output_preview) when reading priors", async () => {
    llmState.llm = { generate: async () => "merged" };
    intendState.rt = {
      bus: {
        redis: {
          xrange: async () => [
            [
              "1-0",
              {
                e: JSON.stringify({
                  type: "RESOLUTION",
                  payload: {
                    intention_id: "int_other",
                    state_diff: { output_preview: "fallback content" },
                  },
                }),
              },
            ],
          ],
        },
      },
    };
    const p = new AutoMergePolicy();
    const action = await p.resolve(makeHandle(), [makeConflict()], {
      content: "draft",
    });
    expect(action.decision).toBe(MergeDecision.MERGED);
  });

  it("respects custom contentKey", async () => {
    llmState.llm = { generate: async () => "merged" };
    intendState.rt = {
      bus: {
        redis: {
          xrange: async () => [
            [
              "1-0",
              {
                e: JSON.stringify({
                  type: "RESOLUTION",
                  payload: {
                    intention_id: "int_other",
                    state_diff: { body: "prior body" },
                  },
                }),
              },
            ],
          ],
        },
      },
    };
    const p = new AutoMergePolicy({ contentKey: "body" });
    const action = await p.resolve(makeHandle(), [makeConflict()], {
      body: "my body",
    });
    expect(action.decision).toBe(MergeDecision.MERGED);
    expect(action.mergedAction?.["body"]).toBe("merged");
  });

  it("falls back when xrange throws", async () => {
    llmState.llm = { generate: async () => "merged" };
    intendState.rt = {
      bus: {
        redis: {
          xrange: async () => {
            throw new Error("redis down");
          },
        },
      },
    };
    const p = new AutoMergePolicy();
    const action = await p.resolve(makeHandle(), [makeConflict()], {
      content: "draft",
    });
    expect(action.decision).toBe(MergeDecision.PROCEED);
  });
});
