/**
 * Unit tests for the v0.2 OpenClaw framework adapter.
 *
 * Strategy: partially mock `../intend.js` so we keep the real
 * `_getOrInitRuntime` / `shutdown` / `_runtime` exports (which `install.ts`
 * pulls in) but swap `intendWith` for a recording stub. That lets us drive
 * the wrapper's policy / conflict / merge paths without standing up a real
 * Bus or Agent.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mock intend BEFORE importing modules that depend on it.
// ---------------------------------------------------------------------------
type IntendOpts = {
  scope: string[];
  agent: string;
  session?: string;
  expectedOutcome?: string;
  blocking?: boolean;
  gateMs?: number;
  proposedAction?: Record<string, unknown>;
};

interface MockHandle {
  intentionId: string;
  scope: string[];
  agentId: string;
  sessionId: string;
  conflicts: unknown[];
  stateDiff: Record<string, unknown>;
  sideEffects: string[];
  outcome: "success" | "failure" | "partial";
  errorMessage?: string;
  mergedAction: Record<string, unknown> | null;
  policyRationale?: string;
  aborted: boolean;
  beliefsEmitted: unknown[];
  divergences: unknown[];
  hasConflicts: boolean;
  setStateDiff(d: Record<string, unknown>): void;
  addSideEffect(s: string): void;
  markFailed(m?: string): void;
  pivot(): Promise<void>;
  dispose(): Promise<void>;
}

interface MockState {
  conflicts: unknown[];
  customMergedAction?: Record<string, unknown> | null;
  calls: Array<{ opts: IntendOpts; handleRefs: MockHandle[] }>;
  throwBeforeRun?: Error;
}

const _mockState: MockState = {
  conflicts: [],
  calls: [],
};

function _resetMockState(): void {
  _mockState.conflicts = [];
  _mockState.calls = [];
  delete _mockState.customMergedAction;
  delete _mockState.throwBeforeRun;
}

function _makeHandle(opts: IntendOpts): MockHandle {
  const conflicts = [..._mockState.conflicts];
  const handle: MockHandle = {
    intentionId: conflicts.length ? "intent-with-conflict" : "intent-clean",
    scope: [...opts.scope],
    agentId: opts.agent,
    sessionId: opts.session ?? "default_session",
    conflicts,
    stateDiff: {},
    sideEffects: [],
    outcome: "success",
    mergedAction:
      _mockState.customMergedAction !== undefined
        ? _mockState.customMergedAction
        : null,
    aborted: false,
    beliefsEmitted: [],
    divergences: [],
    get hasConflicts() {
      return conflicts.length > 0;
    },
    setStateDiff(d) {
      Object.assign(this.stateDiff, d);
    },
    addSideEffect(s) {
      this.sideEffects.push(s);
    },
    markFailed(m) {
      this.outcome = "failure";
      if (m) this.errorMessage = m.slice(0, 200);
    },
    async pivot() {
      /* no-op */
    },
    async dispose() {
      /* no-op */
    },
  };
  return handle;
}

vi.mock("../intend.js", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    intendWith: vi.fn(
      async <T>(
        opts: IntendOpts,
        fn: (h: MockHandle) => Promise<T>,
      ): Promise<T> => {
        if (_mockState.throwBeforeRun) {
          throw _mockState.throwBeforeRun;
        }
        const handle = _makeHandle(opts);
        const callRecord = { opts, handleRefs: [handle] };
        _mockState.calls.push(callRecord);
        try {
          const result = await fn(handle);
          return result;
        } catch (e) {
          if (handle.outcome === "success") {
            handle.markFailed((e as Error)?.message ?? String(e));
          }
          throw e;
        } finally {
          await handle.dispose();
        }
      },
    ),
  };
});

// Now safe to import — the mock is in place.
import { _FRAMEWORK_REGISTRY, install, shutdown } from "../install.js";
import {
  installOpenClaw,
  wrapExtensionWithSynapse,
  _getOpenClawState,
  _resetOpenClawState,
  type OpenClawExtension,
} from "./openclaw.js";
import type { Bus } from "../bus.js";

// Tiny stub Bus — we never actually publish; intendWith is mocked.
const fakeBus = {} as unknown as Bus;

beforeEach(async () => {
  await shutdown();
  _resetMockState();
  _resetOpenClawState();
  // Re-register in case a previous test cleared the registry.
  installOpenClaw();
});

afterEach(async () => {
  vi.clearAllMocks();
  await shutdown();
});

// ---------------------------------------------------------------------------
// 1. registerFramework wires under "openclaw"
// ---------------------------------------------------------------------------
describe("openclaw framework registration", () => {
  it("registers under the name 'openclaw'", () => {
    expect(_FRAMEWORK_REGISTRY.has("openclaw")).toBe(true);
    const fn = _FRAMEWORK_REGISTRY.get("openclaw");
    expect(typeof fn).toBe("function");
  });
});

// ---------------------------------------------------------------------------
// 2. install_fn returns hooksInstalled correctly
// ---------------------------------------------------------------------------
describe("install({ framework: 'openclaw' })", () => {
  it("returns hooksInstalled=['openclaw'] and marks state installed", () => {
    const r = install({ framework: "openclaw", auto: false });
    expect(r.framework).toBe("openclaw");
    expect(r.hooksInstalled).toEqual(["openclaw"]);
    expect(_getOpenClawState().installed).toBe(true);
  });

  it("forwards frameworkOpts to the install fn", () => {
    install({
      framework: "openclaw",
      frameworkOpts: { customField: "x" },
      auto: false,
    });
    expect(_getOpenClawState().options).toMatchObject({ customField: "x" });
  });
});

// ---------------------------------------------------------------------------
// 3. wrapExtensionWithSynapse routes write tools through intendWith
// ---------------------------------------------------------------------------
describe("wrapExtensionWithSynapse — write tool routing", () => {
  it("routes write tools through intendWith()", async () => {
    const inner = vi.fn().mockResolvedValue("written-ok");
    const ext: OpenClawExtension = {
      name: "browser",
      tools: [
        {
          name: "write_file",
          description: "write a file",
          isWrite: true,
          handler: inner,
        },
      ],
    };
    const wrapped = wrapExtensionWithSynapse(ext, {
      bus: fakeBus,
      sessionId: "user-1",
    });
    const result = await wrapped.tools[0]!.handler({ path: "x.md", body: "hi" });
    expect(result).toBe("written-ok");
    expect(_mockState.calls).toHaveLength(1);
    const call = _mockState.calls[0]!;
    expect(call.opts.agent).toBe("openclaw");
    expect(call.opts.session).toBe("user-1");
    expect(call.opts.scope).toEqual(["repo.fs.x.md:w"]);
    expect(call.opts.proposedAction).toMatchObject({
      tool: "write_file",
      args: { path: "x.md", body: "hi" },
    });
    expect(inner).toHaveBeenCalledOnce();
    // Wrapper should set output_preview on stateDiff
    expect(call.handleRefs[0]!.stateDiff).toMatchObject({
      output_preview: expect.stringContaining("written-ok"),
    });
  });
});

// ---------------------------------------------------------------------------
// 4. Read tools bypass Synapse cleanly
// ---------------------------------------------------------------------------
describe("wrapExtensionWithSynapse — read tool bypass", () => {
  it("read tools (isWrite=false) skip intendWith entirely", async () => {
    const inner = vi.fn().mockResolvedValue("read-result");
    const ext: OpenClawExtension = {
      name: "fs",
      tools: [
        {
          name: "read_file",
          isWrite: false,
          handler: inner,
        },
      ],
    };
    const wrapped = wrapExtensionWithSynapse(ext, {
      bus: fakeBus,
      sessionId: "u1",
    });
    const result = await wrapped.tools[0]!.handler({ path: "a.md" });
    expect(result).toBe("read-result");
    expect(_mockState.calls).toHaveLength(0);
    expect(inner).toHaveBeenCalledOnce();
    // The wrapper should have returned the original tool object — same handler ref
    expect(wrapped.tools[0]).toBe(ext.tools[0]);
  });
});

// ---------------------------------------------------------------------------
// 5. Multiple tools share scope inference
// ---------------------------------------------------------------------------
describe("wrapExtensionWithSynapse — multi-tool scope inference", () => {
  it("each write tool gets its own scope from defaultScope", async () => {
    const ext: OpenClawExtension = {
      name: "multi",
      tools: [
        {
          name: "write_x",
          isWrite: true,
          handler: vi.fn().mockResolvedValue("ok-x"),
        },
        {
          name: "write_y",
          isWrite: true,
          handler: vi.fn().mockResolvedValue("ok-y"),
        },
      ],
    };
    const wrapped = wrapExtensionWithSynapse(ext, {
      bus: fakeBus,
      sessionId: "u1",
    });
    await wrapped.tools[0]!.handler({});
    await wrapped.tools[1]!.handler({ path: "/tmp/y.txt" });
    expect(_mockState.calls).toHaveLength(2);
    expect(_mockState.calls[0]!.opts.scope).toEqual(["openclaw.tool.write_x:w"]);
    expect(_mockState.calls[1]!.opts.scope).toEqual(["repo.fs.tmp/y.txt:w"]);
  });
});

// ---------------------------------------------------------------------------
// 6. Tool failure marks IntentionHandle as failed
// ---------------------------------------------------------------------------
describe("wrapExtensionWithSynapse — failure marking", () => {
  it("inner tool throwing marks the handle outcome=failure", async () => {
    const ext: OpenClawExtension = {
      name: "x",
      tools: [
        {
          name: "delete_thing",
          isWrite: true,
          handler: vi.fn().mockRejectedValue(new Error("boom")),
        },
      ],
    };
    const wrapped = wrapExtensionWithSynapse(ext, {
      bus: fakeBus,
      sessionId: "s",
    });
    await expect(wrapped.tools[0]!.handler({})).rejects.toThrow("boom");
    expect(_mockState.calls).toHaveLength(1);
    const handle = _mockState.calls[0]!.handleRefs[0]!;
    expect(handle.outcome).toBe("failure");
    expect(handle.errorMessage).toContain("boom");
  });
});

// ---------------------------------------------------------------------------
// 7. Conflict path with auto_merge produces merged result
// ---------------------------------------------------------------------------
describe("wrapExtensionWithSynapse — auto_merge path", () => {
  it("uses mergedAction.args when policy fills it", async () => {
    // Simulate a conflict + a policy that filled mergedAction.
    _mockState.conflicts = [
      {
        intention_id: "x",
        conflicting_intentions: [],
        kind: "scope_overlap",
        suggested_resolution: "use merged",
      },
    ];
    _mockState.customMergedAction = {
      tool: "edit_file",
      args: { path: "a.md", body: "merged-body" },
    };

    const inner = vi.fn().mockImplementation(async (args) => {
      // The wrapper should pass us mergedAction.args, not the original args.
      return `wrote: ${args["body"]}`;
    });
    const ext: OpenClawExtension = {
      name: "fs",
      tools: [
        {
          name: "edit_file",
          isWrite: true,
          handler: inner,
        },
      ],
    };
    const wrapped = wrapExtensionWithSynapse(ext, {
      bus: fakeBus,
      sessionId: "s",
      // failOnConflict=false so the wrapper proceeds through the conflict
      // and uses the merged action.
      failOnConflict: false,
    });
    const result = await wrapped.tools[0]!.handler({
      path: "a.md",
      body: "original-body",
    });
    expect(result).toBe("wrote: merged-body");
    expect(inner).toHaveBeenCalledWith(
      expect.objectContaining({ body: "merged-body" }),
      undefined,
    );
  });
});

// ---------------------------------------------------------------------------
// 8. Custom isWriteTool predicate honored
// ---------------------------------------------------------------------------
describe("wrapExtensionWithSynapse — custom isWriteTool", () => {
  it("uses the predicate to decide which tools to wrap", async () => {
    const ext: OpenClawExtension = {
      name: "weird",
      tools: [
        // Default heuristic would treat 'fetch_data' as read (no write keywords)
        {
          name: "fetch_data",
          handler: vi.fn().mockResolvedValue("data"),
        },
        {
          name: "ping",
          handler: vi.fn().mockResolvedValue("pong"),
        },
      ],
    };
    const wrapped = wrapExtensionWithSynapse(ext, {
      bus: fakeBus,
      sessionId: "s",
      // Force fetch_data to be treated as a write; ping stays read.
      isWriteTool: (t) => t.name === "fetch_data",
    });
    await wrapped.tools[0]!.handler({});
    await wrapped.tools[1]!.handler({});
    expect(_mockState.calls).toHaveLength(1);
    expect(_mockState.calls[0]!.opts.proposedAction).toMatchObject({
      tool: "fetch_data",
    });
  });
});

// ---------------------------------------------------------------------------
// 9. Custom scopeFromCall override honored
// ---------------------------------------------------------------------------
describe("wrapExtensionWithSynapse — custom scopeFromCall", () => {
  it("custom scope function drives the scope claim", async () => {
    const ext: OpenClawExtension = {
      name: "weird",
      tools: [
        {
          name: "send_email",
          isWrite: true,
          handler: vi.fn().mockResolvedValue("sent"),
        },
      ],
    };
    const wrapped = wrapExtensionWithSynapse(ext, {
      bus: fakeBus,
      sessionId: "s",
      scopeFromCall: (tool, args) => [
        `outbox.${args["recipient"]}:w`,
        `tool.${tool.name}:w`,
      ],
    });
    await wrapped.tools[0]!.handler({ recipient: "alice@x.com" });
    expect(_mockState.calls).toHaveLength(1);
    expect(_mockState.calls[0]!.opts.scope).toEqual([
      "outbox.alice@x.com:w",
      "tool.send_email:w",
    ]);
  });
});

// ---------------------------------------------------------------------------
// 10. Backward-compat smoke test: v0.1 public API still works as before
// ---------------------------------------------------------------------------
describe("wrapExtensionWithSynapse — v0.1 backward compat", () => {
  it("public API shape unchanged: returns extension w/ wrapped tools", async () => {
    const ext: OpenClawExtension = {
      name: "compat",
      tools: [
        {
          name: "create_thing",
          isWrite: true,
          handler: vi.fn().mockResolvedValue({ id: 42 }),
        },
      ],
    };
    const wrapped = wrapExtensionWithSynapse(ext, {
      bus: fakeBus,
      sessionId: "session-x",
      agentId: "custom-agent",
      gateMs: 25,
    });
    expect(wrapped.name).toBe("compat+synapse");
    expect(wrapped.tools).toHaveLength(1);
    expect(wrapped.tools[0]!.name).toBe("create_thing");
    const result = await wrapped.tools[0]!.handler({ x: 1 });
    expect(result).toEqual({ id: 42 });
    expect(_mockState.calls[0]!.opts.agent).toBe("custom-agent");
    expect(_mockState.calls[0]!.opts.gateMs).toBe(25);
  });
});

// ---------------------------------------------------------------------------
// 11. failOnConflict=true surfaces a CONFLICT as an error
// ---------------------------------------------------------------------------
describe("wrapExtensionWithSynapse — failOnConflict=true", () => {
  it("throws when a conflict is detected and failOnConflict is true", async () => {
    _mockState.conflicts = [
      {
        intention_id: "x",
        conflicting_intentions: [],
        kind: "scope_overlap",
        suggested_resolution: "back off",
      },
    ];
    const inner = vi.fn().mockResolvedValue("should-not-run");
    const ext: OpenClawExtension = {
      name: "x",
      tools: [
        {
          name: "write_thing",
          isWrite: true,
          handler: inner,
        },
      ],
    };
    const wrapped = wrapExtensionWithSynapse(ext, {
      bus: fakeBus,
      sessionId: "s",
      failOnConflict: true,
    });
    await expect(wrapped.tools[0]!.handler({})).rejects.toThrow(
      /Synapse CONFLICT on write_thing/,
    );
    expect(inner).not.toHaveBeenCalled();
  });
});
