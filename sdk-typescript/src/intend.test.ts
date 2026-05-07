/**
 * Unit tests for synapse.intend / IntentionHandle / runtime helpers.
 *
 * The TS port has no real Redis dependency in offline mode — these tests
 * exercise that path + the policy / handle / dispose machinery using
 * stub MergePolicy instances.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  IntentionHandle,
  _getAgent,
  _getOrInitRuntime,
  _runtime,
  intend,
  intendWith,
  shutdown,
} from "./intend.js";
import {
  MergeDecision,
  MergePolicy,
  SynapseConflict,
  type MergeAction,
  type IntentionHandleLike,
} from "./policies/base.js";
import type { Conflict } from "./types.js";

// ---------------------------------------------------------------------------
// Helpers — tiny stubs for tests that drive intend()'s policy code path.
// ---------------------------------------------------------------------------
class StubProceedPolicy extends MergePolicy {
  override name = "stub_proceed";
  resolved = 0;
  async resolve(): Promise<MergeAction> {
    this.resolved++;
    return { decision: MergeDecision.PROCEED, rationale: "stub-proceed" };
  }
}

class StubAbortPolicy extends MergePolicy {
  override name = "stub_abort";
  async resolve(): Promise<MergeAction> {
    return { decision: MergeDecision.ABORT, rationale: "stub-abort-rationale" };
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
      mergedAction: { ...(proposedAction ?? {}), merged: true },
      rationale: "stub-merge",
    };
  }
}

class StubWaitPolicy extends MergePolicy {
  override name = "stub_wait";
  async resolve(): Promise<MergeAction> {
    return {
      decision: MergeDecision.WAIT,
      rationale: "stub-wait",
      waitTimeoutMs: 5,
    };
  }
}

// ---------------------------------------------------------------------------
// Test setup: ensure offline mode by default; reset runtime between tests.
// ---------------------------------------------------------------------------
const SAVED_ENV = { ...process.env };

beforeEach(async () => {
  await shutdown();
  delete process.env["SYNAPSE_REDIS_URL"];
  delete process.env["SYNAPSE_POSTGRES_DSN"];
  delete process.env["SYNAPSE_SESSION_ID"];
  delete process.env["SYNAPSE_DEFAULT_AGENT_ID"];
});

afterEach(async () => {
  await shutdown();
  Object.assign(process.env, SAVED_ENV);
});

// ---------------------------------------------------------------------------
// Runtime
// ---------------------------------------------------------------------------
describe("_getOrInitRuntime", () => {
  it("returns offline mode when no SYNAPSE_REDIS_URL set", () => {
    const rt = _getOrInitRuntime();
    expect(rt.mode).toBe("offline");
    expect(rt.bus).toBeUndefined();
  });

  it("is idempotent — second call returns the same runtime", () => {
    const a = _getOrInitRuntime();
    const b = _getOrInitRuntime();
    expect(a).toBe(b);
    expect(a.mode).toBe("offline");
  });

  it("picks up busUrl arg over env", () => {
    // We don't actually connect — just check the runtime config.
    const rt = _getOrInitRuntime({ busUrl: "redis://test:6379/0" });
    expect(rt.mode).toBe("live");
    expect(rt.busUrl).toBe("redis://test:6379/0");
    expect(rt.bus).toBeDefined();
  });

  it("falls back to env SYNAPSE_REDIS_URL", () => {
    process.env["SYNAPSE_REDIS_URL"] = "redis://envhost:6379/0";
    const rt = _getOrInitRuntime();
    expect(rt.mode).toBe("live");
    expect(rt.busUrl).toBe("redis://envhost:6379/0");
  });
});

describe("_getAgent", () => {
  it("returns null in offline mode", async () => {
    const a = await _getAgent("foo", "s1");
    expect(a).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// IntentionHandle (unit, no agent involved)
// ---------------------------------------------------------------------------
describe("IntentionHandle", () => {
  it("hasConflicts is false when no conflicts", () => {
    const h = new IntentionHandle({
      intentionId: "x",
      scope: ["a:r"],
      agentId: "a1",
      sessionId: "s1",
    });
    expect(h.hasConflicts).toBe(false);
  });

  it("hasConflicts true when conflicts assigned", () => {
    const h = new IntentionHandle({
      intentionId: "x",
      scope: ["a:r"],
      agentId: "a1",
      sessionId: "s1",
    });
    h.conflicts = [
      {
        intention_id: "x",
        conflicting_intentions: [],
        kind: "scope_overlap",
      } as Conflict,
    ];
    expect(h.hasConflicts).toBe(true);
  });

  it("setStateDiff merges, addSideEffect appends", () => {
    const h = new IntentionHandle({
      intentionId: "x",
      scope: [],
      agentId: "a",
      sessionId: "s",
    });
    h.setStateDiff({ a: 1 });
    h.setStateDiff({ b: 2 });
    expect(h.stateDiff).toEqual({ a: 1, b: 2 });
    h.addSideEffect("wrote-file");
    h.addSideEffect("sent-email");
    expect(h.sideEffects).toEqual(["wrote-file", "sent-email"]);
  });

  it("markFailed sets outcome+errorMessage (truncated to 200)", () => {
    const h = new IntentionHandle({
      intentionId: "x",
      scope: [],
      agentId: "a",
      sessionId: "s",
    });
    const long = "x".repeat(500);
    h.markFailed(long);
    expect(h.outcome).toBe("failure");
    expect(h.errorMessage).toHaveLength(200);
  });

  it("default outcome is success, aborted false", () => {
    const h = new IntentionHandle({
      intentionId: "x",
      scope: [],
      agentId: "a",
      sessionId: "s",
    });
    expect(h.outcome).toBe("success");
    expect(h.aborted).toBe(false);
    expect(h.beliefsEmitted).toEqual([]);
    expect(h.divergences).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// intend() — offline mode (no Redis): body still runs, no envelopes.
// ---------------------------------------------------------------------------
describe("intend() offline mode", () => {
  it("returns a usable handle in offline mode", async () => {
    const h = await intend({
      scope: ["repo.fs.x:w"],
      agent: "agent-a",
      expectedOutcome: "test",
    });
    expect(h.scope).toEqual(["repo.fs.x:w"]);
    expect(h.agentId).toBe("agent-a");
    expect(h.intentionId).toBe(""); // offline => no real id
    expect(h.hasConflicts).toBe(false);
    await h.dispose();
  });

  it("setStateDiff / addSideEffect on the live handle work", async () => {
    const h = await intend({ scope: [], agent: "a" });
    h.setStateDiff({ linesChanged: 47 });
    h.addSideEffect("file:x");
    expect(h.stateDiff).toEqual({ linesChanged: 47 });
    expect(h.sideEffects).toEqual(["file:x"]);
    await h.dispose();
  });

  it("session_id falls back to env SYNAPSE_SESSION_ID", async () => {
    process.env["SYNAPSE_SESSION_ID"] = "env-session-9";
    const h = await intend({ scope: [], agent: "a" });
    expect(h.sessionId).toBe("env-session-9");
    await h.dispose();
  });

  it("session_id falls back to default_session", async () => {
    const h = await intend({ scope: [], agent: "a" });
    expect(h.sessionId).toBe("default_session");
    await h.dispose();
  });

  it("explicit session arg wins over env", async () => {
    process.env["SYNAPSE_SESSION_ID"] = "env-loser";
    const h = await intend({ scope: [], agent: "a", session: "explicit-x" });
    expect(h.sessionId).toBe("explicit-x");
    await h.dispose();
  });
});

// ---------------------------------------------------------------------------
// intendWith() — callback form
// ---------------------------------------------------------------------------
describe("intendWith()", () => {
  it("invokes callback with handle and returns its value", async () => {
    const result = await intendWith(
      { scope: [], agent: "a" },
      async (h) => {
        expect(h).toBeInstanceOf(IntentionHandle);
        h.setStateDiff({ ok: true });
        return 42;
      },
    );
    expect(result).toBe(42);
  });

  it("markFailed on thrown exception", async () => {
    let captured: IntentionHandle | null = null;
    await expect(
      intendWith({ scope: [], agent: "a" }, async (h) => {
        captured = h;
        throw new Error("boom");
      }),
    ).rejects.toThrow("boom");
    expect(captured).not.toBeNull();
    expect(captured!.outcome).toBe("failure");
    expect(captured!.errorMessage).toContain("boom");
  });
});

// ---------------------------------------------------------------------------
// Conflict + policy paths — drive the runtime by manually injecting
// conflicts into a handle through a custom flow:
//   1) we create our own handle, register it as having conflicts,
//   2) simulate the policy invocation by calling intend()'s code path.
// Since offline mode never produces conflicts via emit_intention, we
// fake the conflicts by monkey-patching _getAgent through the runtime.
// ---------------------------------------------------------------------------
describe("intend() conflict + policy", () => {
  function makeFakeAgent(conflicts: Conflict[]): {
    agent: unknown;
    emitResolutionCalls: Array<Record<string, unknown>>;
  } {
    const emitResolutionCalls: Array<Record<string, unknown>> = [];
    const agent = {
      emitIntention: vi
        .fn()
        .mockResolvedValue(["fake-intention-id-01", conflicts]),
      emitResolution: vi.fn(async (args: Record<string, unknown>) => {
        emitResolutionCalls.push(args);
      }),
      emitBelief: vi.fn(),
    };
    return { agent, emitResolutionCalls };
  }

  function patchRuntimeWithFakeAgent(
    fakeAgent: unknown,
  ): { restore: () => void } {
    // Force live mode so _getAgent returns our fake.
    _runtime.mode = "live";
    _runtime.bus = undefined;
    _runtime.connected = true;
    const agents = new Map<string, unknown>();
    agents.set("default_session::a", fakeAgent);
    agents.set("s::a", fakeAgent);
    _runtime.agents = agents as unknown as Map<string, never>;
    return {
      restore: () => {
        // shutdown() in afterEach handles full cleanup.
      },
    };
  }

  it("no conflict → no policy invocation, no dispose error", async () => {
    const { agent } = makeFakeAgent([]);
    patchRuntimeWithFakeAgent(agent);
    const stub = new StubProceedPolicy();
    const h = await intend({
      scope: ["x:w"],
      agent: "a",
      mergePolicy: stub,
    });
    expect(stub.resolved).toBe(0);
    expect(h.hasConflicts).toBe(false);
    expect(h.intentionId).toBe("fake-intention-id-01");
    await h.dispose();
  });

  it("conflict + StubMergePolicy → fills mergedAction", async () => {
    const conflicts: Conflict[] = [
      {
        intention_id: "fake-intention-id-01",
        conflicting_intentions: [
          { intention_id: "other", agent_id: "b", scope: ["x:w"] },
        ],
        kind: "scope_overlap",
      },
    ];
    const { agent } = makeFakeAgent(conflicts);
    patchRuntimeWithFakeAgent(agent);
    const h = await intend({
      scope: ["x:w"],
      agent: "a",
      mergePolicy: new StubMergePolicy(),
      proposedAction: { content: "draft" },
    });
    expect(h.hasConflicts).toBe(true);
    expect(h.mergedAction).toEqual({ content: "draft", merged: true });
    expect(h.policyRationale).toBe("stub-merge");
    await h.dispose();
  });

  it("conflict + StubAbortPolicy → throws SynapseConflict", async () => {
    const conflicts: Conflict[] = [
      {
        intention_id: "fake-intention-id-01",
        conflicting_intentions: [],
        kind: "scope_overlap",
      },
    ];
    const { agent, emitResolutionCalls } = makeFakeAgent(conflicts);
    patchRuntimeWithFakeAgent(agent);
    await expect(
      intend({
        scope: ["x:w"],
        agent: "a",
        mergePolicy: new StubAbortPolicy(),
      }),
    ).rejects.toBeInstanceOf(SynapseConflict);
    // Resolution emitted with failure outcome.
    expect(emitResolutionCalls.length).toBe(1);
    expect(emitResolutionCalls[0]!.outcome).toBe("failure");
  });

  it("conflict + StubWaitPolicy → sleeps then proceeds", async () => {
    const conflicts: Conflict[] = [
      {
        intention_id: "fake-intention-id-01",
        conflicting_intentions: [],
        kind: "scope_overlap",
      },
    ];
    const { agent } = makeFakeAgent(conflicts);
    patchRuntimeWithFakeAgent(agent);
    const t0 = Date.now();
    const h = await intend({
      scope: ["x:w"],
      agent: "a",
      mergePolicy: new StubWaitPolicy(),
    });
    const elapsed = Date.now() - t0;
    expect(elapsed).toBeGreaterThanOrEqual(4); // ~5ms wait
    expect(h.hasConflicts).toBe(true);
    expect(h.policyRationale).toBe("stub-wait");
    await h.dispose();
  });

  it("critical_scopes hard-blocks via SynapseConflict", async () => {
    const conflicts: Conflict[] = [
      {
        intention_id: "fake-intention-id-01",
        conflicting_intentions: [],
        kind: "scope_overlap",
      },
    ];
    const { agent } = makeFakeAgent(conflicts);
    patchRuntimeWithFakeAgent(agent);
    await expect(
      intend({
        scope: ["billing.charge:w"],
        agent: "a",
        criticalScopes: ["billing.*"],
        mergePolicy: new StubProceedPolicy(),
      }),
    ).rejects.toBeInstanceOf(SynapseConflict);
  });

  it("RESOLUTION emitted on dispose with state_diff + side_effects", async () => {
    const { agent, emitResolutionCalls } = makeFakeAgent([]);
    patchRuntimeWithFakeAgent(agent);
    const h = await intend({ scope: ["x:w"], agent: "a" });
    h.setStateDiff({ lines: 47 });
    h.addSideEffect("wrote-file");
    await h.dispose();
    expect(emitResolutionCalls.length).toBe(1);
    expect(emitResolutionCalls[0]!.intentionId).toBe("fake-intention-id-01");
    expect(emitResolutionCalls[0]!.outcome).toBe("success");
    expect(emitResolutionCalls[0]!.state_diff).toMatchObject({ lines: 47 });
    expect(emitResolutionCalls[0]!.side_effects).toEqual(["wrote-file"]);
  });

  it("RESOLUTION not double-emitted when dispose called twice", async () => {
    const { agent, emitResolutionCalls } = makeFakeAgent([]);
    patchRuntimeWithFakeAgent(agent);
    const h = await intend({ scope: ["x:w"], agent: "a" });
    await h.dispose();
    await h.dispose();
    expect(emitResolutionCalls.length).toBe(1);
  });

  it("intendWith on conflict+abort still finalizes (no double emit)", async () => {
    const conflicts: Conflict[] = [
      {
        intention_id: "fake-intention-id-01",
        conflicting_intentions: [],
        kind: "scope_overlap",
      },
    ];
    const { agent, emitResolutionCalls } = makeFakeAgent(conflicts);
    patchRuntimeWithFakeAgent(agent);
    await expect(
      intendWith(
        { scope: ["x:w"], agent: "a", mergePolicy: new StubAbortPolicy() },
        async () => {
          throw new Error("should not be called");
        },
      ),
    ).rejects.toBeInstanceOf(SynapseConflict);
    // Only the abort path's emitResolution should fire — dispose
    // sees aborted=true and skips its own emit.
    expect(emitResolutionCalls.length).toBe(1);
    expect(emitResolutionCalls[0]!.outcome).toBe("failure");
  });

  it("Symbol.asyncDispose path emits RESOLUTION", async () => {
    const { agent, emitResolutionCalls } = makeFakeAgent([]);
    patchRuntimeWithFakeAgent(agent);
    {
      // Mimic `await using` semantics by manually invoking the disposer.
      const h = await intend({ scope: ["x:w"], agent: "a" });
      h.setStateDiff({ ok: 1 });
      await h[Symbol.asyncDispose]();
    }
    expect(emitResolutionCalls.length).toBe(1);
    expect(emitResolutionCalls[0]!.state_diff).toMatchObject({ ok: 1 });
  });
});
