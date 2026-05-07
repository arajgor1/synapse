/**
 * Tests for the v0.2 frameworks/paperclip.ts adapter.
 *
 * Validates:
 *   - registerFramework wires "paperclip" alias
 *   - install_fn stashes defaults that wrapAdapterWithSynapse picks up
 *   - end-to-end intend() flow over the v0.1-compatible wrapper
 *   - merge policy ABORT path → throws SynapseConflict (or AdapterError when
 *     failOnConflict=true)
 *   - merge policy MERGED path → uses mergedAction
 *   - failOnConflict=false legacy path still works
 *   - Multiple Paperclip task.agentId values create distinct Synapse agents
 *   - COST_REPORT envelope still emitted on token usage
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  _FRAMEWORK_REGISTRY,
  install,
  shutdown,
} from "../install.js";
import { _runtime } from "../intend.js";
import {
  MergeDecision,
  MergePolicy,
  SynapseConflict,
  type MergeAction,
  type IntentionHandleLike,
} from "../policies/base.js";
import type { Conflict } from "../types.js";
import {
  _paperclipDefaults,
  _resetPaperclipDefaults,
} from "./paperclip.js";
import {
  type PaperclipAdapter,
  wrapAdapterWithSynapse,
} from "../integrations/paperclip.js";
import type { Bus } from "../bus.js";

// ---------------------------------------------------------------------------
// In-memory fake Bus for unit tests — captures published envelopes
// and lets tests inject inbox messages.
// ---------------------------------------------------------------------------
function makeFakeBus(): Bus & { _published: any[]; _inbox: Map<string, any[]> } {
  const published: any[] = [];
  const inbox = new Map<string, any[]>();
  return {
    async connect() {},
    async close() {},
    async publishSession(envelope: any) {
      published.push(envelope);
      return "1-0";
    },
    async publishInbox(agentId: string, envelope: any) {
      const arr = inbox.get(agentId) ?? [];
      arr.push(envelope);
      inbox.set(agentId, arr);
      return "1-0";
    },
    async ensureGroup() {},
    async drainInbox(agentId: string) {
      const arr = inbox.get(agentId) ?? [];
      inbox.set(agentId, []);
      return arr.map((e, i) => [`1-${i}`, e] as [string, any]);
    },
    _published: published,
    _inbox: inbox,
  } as unknown as Bus & { _published: any[]; _inbox: Map<string, any[]> };
}

// ---------------------------------------------------------------------------
// Stub policies for driving the conflict paths.
// ---------------------------------------------------------------------------
class StubAbortPolicy extends MergePolicy {
  override name = "stub_abort";
  async resolve(): Promise<MergeAction> {
    return { decision: MergeDecision.ABORT, rationale: "stub-abort" };
  }
}
class StubMergePolicy extends MergePolicy {
  override name = "stub_merge";
  async resolve(
    _h: IntentionHandleLike,
    _c: Conflict[],
    proposedAction?: Record<string, unknown>,
  ): Promise<MergeAction> {
    return {
      decision: MergeDecision.MERGED,
      mergedAction: { ...(proposedAction ?? {}), prompt: "merged-prompt" },
      rationale: "stub-merge",
    };
  }
}

// ---------------------------------------------------------------------------
// Conflict-injection helper: pre-seed _runtime.agents with a fake agent
// whose emitIntention always returns conflicts, so intend() takes the
// policy code path without needing a real bus.
// ---------------------------------------------------------------------------
function seedFakeAgent(
  sessionId: string,
  agentId: string,
  conflicts: Conflict[],
): {
  emitIntentionCalls: Array<Record<string, unknown>>;
  emitResolutionCalls: Array<Record<string, unknown>>;
} {
  const emitIntentionCalls: Array<Record<string, unknown>> = [];
  const emitResolutionCalls: Array<Record<string, unknown>> = [];
  const fakeAgent = {
    id: agentId,
    session: sessionId,
    emitIntention: vi.fn(async (args: Record<string, unknown>) => {
      emitIntentionCalls.push(args);
      return ["fake-intention-id-01", conflicts] as [string, Conflict[]];
    }),
    emitResolution: vi.fn(async (args: Record<string, unknown>) => {
      emitResolutionCalls.push(args);
      return "1-0";
    }),
  };
  if (!_runtime.agents) _runtime.agents = new Map();
  _runtime.agents.set(`${sessionId}::${agentId}`, fakeAgent as never);
  return { emitIntentionCalls, emitResolutionCalls };
}

// ---------------------------------------------------------------------------
// Setup / teardown — keep runtime + framework registry clean per-test.
// ---------------------------------------------------------------------------
const SAVED_ENV = { ...process.env };

beforeEach(async () => {
  await shutdown();
  _resetPaperclipDefaults();
  delete process.env["SYNAPSE_REDIS_URL"];
  delete process.env["SYNAPSE_POSTGRES_DSN"];
  delete process.env["SYNAPSE_SESSION_ID"];
  delete process.env["SYNAPSE_DEFAULT_AGENT_ID"];
  // Note: we don't clear _FRAMEWORK_REGISTRY because the "paperclip"
  // registration is a one-shot import-time side effect of ./paperclip.js
  // and tests in this file rely on it staying live.
});

afterEach(async () => {
  await shutdown();
  _resetPaperclipDefaults();
  Object.assign(process.env, SAVED_ENV);
});

// ===========================================================================
// 1. Framework registration
// ===========================================================================
describe("frameworks/paperclip — registration", () => {
  it("registerFramework wires under the 'paperclip' alias", () => {
    expect(_FRAMEWORK_REGISTRY.has("paperclip")).toBe(true);
  });

  it("install({ framework: 'paperclip' }) reports hooksInstalled", () => {
    const r = install({ framework: "paperclip", auto: false });
    expect(r.framework).toBe("paperclip");
    expect(r.hooksInstalled).toEqual(["paperclip"]);
  });

  it("install_fn stashes frameworkOpts on _paperclipDefaults", () => {
    const customScope = (t: { id: string; agentId: string }) => [
      `custom:${t.id}:w`,
    ];
    install({
      framework: "paperclip",
      auto: false,
      frameworkOpts: {
        sessionId: "company_X",
        gateMs: 77,
        scopeFromTask: customScope,
        failOnConflict: false,
        criticalScopes: ["billing.*"],
      },
    });
    expect(_paperclipDefaults.sessionId).toBe("company_X");
    expect(_paperclipDefaults.gateMs).toBe(77);
    expect(_paperclipDefaults.scopeFromTask).toBe(customScope);
    expect(_paperclipDefaults.failOnConflict).toBe(false);
    expect(_paperclipDefaults.criticalScopes).toEqual(["billing.*"]);
  });
});

// ===========================================================================
// 2. End-to-end: wrapAdapterWithSynapse + intend() over fake bus
// ===========================================================================
describe("frameworks/paperclip — wrapAdapterWithSynapse intend() flow", () => {
  it("emits INTENTION + RESOLUTION envelopes via the bus", async () => {
    const bus = makeFakeBus();
    const inner: PaperclipAdapter = {
      type: "anthropic",
      async invoke() {
        return { text: "hello", tokensIn: 10, tokensOut: 5 };
      },
    };
    const wrapped = wrapAdapterWithSynapse(inner, {
      bus,
      sessionId: "company_acme",
      gateMs: 5,
    });
    const resp = await wrapped.invoke({
      task: { id: "t-int-1", agentId: "engineer_a" },
      prompt: "go",
    });
    expect(resp.text).toBe("hello");
    expect(resp.error).toBeUndefined();
    const types = bus._published.map((e) => e.type);
    expect(types).toContain("INTENTION");
    expect(types).toContain("RESOLUTION");
  });

  it("emits COST_REPORT envelope when tokens reported", async () => {
    const bus = makeFakeBus();
    const inner: PaperclipAdapter = {
      type: "openai",
      async invoke() {
        return {
          text: "cost-test",
          tokensIn: 100,
          tokensOut: 50,
          estimatedUsd: 0.002,
        };
      },
    };
    const wrapped = wrapAdapterWithSynapse(inner, {
      bus,
      sessionId: "s-cost",
      gateMs: 5,
    });
    await wrapped.invoke({
      task: { id: "tcost", agentId: "agent_x" },
      prompt: "hi",
    });
    const cost = bus._published.find((e) => e.type === "COST_REPORT");
    expect(cost).toBeDefined();
    expect(cost?.payload?.tokens_billed).toBe(150);
    expect(cost?.payload?.estimated_usd).toBe(0.002);
  });
});

// ===========================================================================
// 3. Conflict + policy paths (uses fake agent injected into _runtime.agents)
// ===========================================================================
describe("frameworks/paperclip — merge policy paths", () => {
  it("MergePolicy ABORT throws SynapseConflict when failOnConflict=false", async () => {
    const bus = makeFakeBus();
    const conflicts: Conflict[] = [
      {
        intention_id: "fake-intention-id-01",
        conflicting_intentions: [
          { intention_id: "rival", agent_id: "b", scope: ["x:w"] },
        ],
        kind: "scope_overlap",
      },
    ];
    seedFakeAgent("session_abort", "alpha", conflicts);
    const inner: PaperclipAdapter = {
      type: "anthropic",
      async invoke() {
        return { text: "should not run" };
      },
    };
    const wrapped = wrapAdapterWithSynapse(inner, {
      bus,
      sessionId: "session_abort",
      gateMs: 5,
      failOnConflict: false,
      mergePolicy: new StubAbortPolicy(),
    });
    await expect(
      wrapped.invoke({
        task: { id: "t-abort", agentId: "alpha" },
        prompt: "go",
      }),
    ).rejects.toBeInstanceOf(SynapseConflict);
  });

  it("MergePolicy ABORT + failOnConflict=true (default) → AdapterError on response", async () => {
    const bus = makeFakeBus();
    const conflicts: Conflict[] = [
      {
        intention_id: "fake-intention-id-01",
        conflicting_intentions: [],
        kind: "scope_overlap",
      },
    ];
    seedFakeAgent("session_abort_legacy", "beta", conflicts);
    const inner: PaperclipAdapter = {
      type: "anthropic",
      async invoke() {
        return { text: "should not run" };
      },
    };
    const wrapped = wrapAdapterWithSynapse(inner, {
      bus,
      sessionId: "session_abort_legacy",
      gateMs: 5,
      mergePolicy: new StubAbortPolicy(),
      // failOnConflict defaults to true
    });
    const resp = await wrapped.invoke({
      task: { id: "t-abort-legacy", agentId: "beta" },
      prompt: "x",
    });
    expect(resp.error?.kind).toBe("synapse_conflict");
  });

  it("MergePolicy MERGED → inner adapter receives merged_action", async () => {
    const bus = makeFakeBus();
    const conflicts: Conflict[] = [
      {
        intention_id: "fake-intention-id-01",
        conflicting_intentions: [],
        kind: "scope_overlap",
      },
    ];
    seedFakeAgent("session_merge", "gamma", conflicts);
    let observedPrompt = "";
    let observedMerged: unknown = null;
    const inner: PaperclipAdapter = {
      type: "anthropic",
      async invoke(req) {
        observedPrompt = req.prompt;
        observedMerged = (req as Record<string, unknown>)["synapseMergedAction"];
        return { text: "ok-merged" };
      },
    };
    const wrapped = wrapAdapterWithSynapse(inner, {
      bus,
      sessionId: "session_merge",
      gateMs: 5,
      mergePolicy: new StubMergePolicy(),
    });
    const resp = await wrapped.invoke({
      task: { id: "t-merge", agentId: "gamma" },
      prompt: "original-prompt",
    });
    expect(resp.text).toBe("ok-merged");
    expect(observedPrompt).toBe("merged-prompt");
    expect(observedMerged).toBeTruthy();
  });

  it("failOnConflict=false (legacy v0.1) without policy still proceeds on conflict", async () => {
    const bus = makeFakeBus();
    const conflicts: Conflict[] = [
      {
        intention_id: "fake-intention-id-01",
        conflicting_intentions: [],
        kind: "scope_overlap",
        overlapping_scopes: ["paperclip.task:t-legacy:w"],
      },
    ];
    seedFakeAgent("session_legacy", "delta", conflicts);
    let invoked = 0;
    const inner: PaperclipAdapter = {
      type: "anthropic",
      async invoke() {
        invoked += 1;
        return { text: "proceeded-anyway" };
      },
    };
    const wrapped = wrapAdapterWithSynapse(inner, {
      bus,
      sessionId: "session_legacy",
      gateMs: 5,
      failOnConflict: false,
      // no mergePolicy → conflict observed but no resolution → proceed
    });
    const resp = await wrapped.invoke({
      task: { id: "t-legacy", agentId: "delta" },
      prompt: "hi",
    });
    expect(invoked).toBe(1);
    expect(resp.text).toBe("proceeded-anyway");
    expect(resp.error).toBeUndefined();
  });
});

// ===========================================================================
// 4. Multi-agent isolation
// ===========================================================================
describe("frameworks/paperclip — multi-agent", () => {
  it("multiple Paperclip task.agentId values create distinct Synapse agents", async () => {
    const bus = makeFakeBus();
    const inner: PaperclipAdapter = {
      type: "anthropic",
      async invoke() {
        return { text: "ok" };
      },
    };
    const wrapped = wrapAdapterWithSynapse(inner, {
      bus,
      sessionId: "session_multi",
      gateMs: 5,
    });

    await wrapped.invoke({
      task: { id: "t-m1", agentId: "agent_one" },
      prompt: "p1",
    });
    await wrapped.invoke({
      task: { id: "t-m2", agentId: "agent_two" },
      prompt: "p2",
    });
    await wrapped.invoke({
      task: { id: "t-m3", agentId: "agent_one" },
      prompt: "p3",
    });

    const cacheKeys = Array.from(_runtime.agents?.keys() ?? []);
    expect(cacheKeys).toContain("session_multi::agent_one");
    expect(cacheKeys).toContain("session_multi::agent_two");
    // Each unique agentId gets exactly one Agent.
    const sessionMatches = cacheKeys.filter((k) =>
      k.startsWith("session_multi::"),
    );
    expect(sessionMatches.length).toBe(2);
  });
});

// ===========================================================================
// 5. install() defaults flow into wrapAdapterWithSynapse
// ===========================================================================
describe("frameworks/paperclip — install() defaults flow", () => {
  it("install-time gateMs / scopeFromTask defaults applied to wrapper", async () => {
    const bus = makeFakeBus();
    const customScope = (t: { id: string; agentId: string }) => [
      `installed:${t.id}:w`,
    ];
    install({
      framework: "paperclip",
      auto: false,
      frameworkOpts: {
        gateMs: 7,
        scopeFromTask: customScope,
      },
    });
    expect(_paperclipDefaults.scopeFromTask).toBe(customScope);
    const inner: PaperclipAdapter = {
      type: "anthropic",
      async invoke() {
        return { text: "ok" };
      },
    };
    const wrapped = wrapAdapterWithSynapse(inner, {
      bus,
      sessionId: "company_install",
      // intentionally no gateMs / scopeFromTask — pulled from defaults
    });
    await wrapped.invoke({
      task: { id: "t-from-install", agentId: "epsilon" },
      prompt: "x",
    });
    const intent = bus._published.find((e) => e.type === "INTENTION");
    expect(intent?.payload?.scope).toEqual(["installed:t-from-install:w"]);
  });
});
