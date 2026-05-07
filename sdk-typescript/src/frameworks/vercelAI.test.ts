/**
 * Unit tests for the Vercel AI SDK adapter.
 *
 * All tests are mock-only — we never load the real `ai` package. We stub
 * `../intend.js` so `intendWith()` becomes a deterministic spy that just
 * threads a fake IntentionHandle through to the inner callback.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Mock intendWith BEFORE importing the adapter — the registration call at
// module-load time uses the real intend.js, but per-call instrumentation will
// pick up the mock. Use vi.hoisted so the spy survives vi.mock hoisting.
const { intendWithMock } = vi.hoisted(() => {
  const fn = async (
    _opts: Record<string, unknown>,
    cb: (h: Record<string, unknown>) => Promise<unknown>,
  ) => {
    const handle = {
      intentionId: "fake-intention-id",
      stateDiff: {} as Record<string, unknown>,
      sideEffects: [] as string[],
      outcome: "success",
      errorMessage: undefined as string | undefined,
      conflicts: [],
      hasConflicts: false,
      setStateDiff(diff: Record<string, unknown>) {
        Object.assign(this.stateDiff, diff);
      },
      addSideEffect(s: string) {
        this.sideEffects.push(s);
      },
      markFailed(m: string) {
        this.outcome = "failure";
        this.errorMessage = m.slice(0, 200);
      },
      async pivot() {},
      async dispose() {},
    };
    return cb(handle);
  };
  // vi is available at hoisted-time
  // @ts-expect-error vi is provided by vitest globals at hoisted-time
  return { intendWithMock: vi.fn(fn) };
});

vi.mock("../intend.js", () => ({
  intendWith: intendWithMock,
  // shape stubs so test imports of types don't blow up (we never call them)
  intend: vi.fn(),
  IntentionHandle: class {},
  shutdown: vi.fn(),
  _runtime: {},
  _getOrInitRuntime: vi.fn(() => ({})),
  getOrInitRuntime: vi.fn(() => ({})),
  _getAgent: vi.fn(),
  getAgent: vi.fn(),
}));

// Now import adapter — registers under registry too.
import {
  _resetVercelAIDefaults,
  _setVercelAIToolFactory,
  inferVercelAIScope,
  synapseTool,
  wrapVercelTools,
  getVercelAICallback,
} from "./index.js";
import { _FRAMEWORK_REGISTRY, install } from "../install.js";

beforeEach(() => {
  intendWithMock.mockClear();
  _resetVercelAIDefaults();
  _setVercelAIToolFactory(undefined);
  delete process.env["SYNAPSE_DEFAULT_AGENT_ID"];
});

afterEach(() => {
  _resetVercelAIDefaults();
  _setVercelAIToolFactory(undefined);
});

// ---------------------------------------------------------------------------
describe("synapseTool factory shape", () => {
  it("returns an object that preserves description/parameters/execute", () => {
    const factoryMock = vi.fn((c: unknown) => ({ ...(c as object), __tagged: true }));
    _setVercelAIToolFactory(factoryMock as never);

    const t = synapseTool({
      name: "write_file",
      description: "Write a file",
      parameters: { type: "object" },
      execute: async () => ({ ok: true }),
    });

    expect(factoryMock).toHaveBeenCalledTimes(1);
    expect(t).toMatchObject({
      description: "Write a file",
      parameters: { type: "object" },
      __tagged: true,
    });
    expect(typeof (t as { execute?: unknown }).execute).toBe("function");
  });

  it("identity factory fallback works when no `ai` package is loaded", () => {
    // No factory injected — synapseTool falls back to identity wrapper.
    const t = synapseTool({
      description: "no-op",
      execute: async () => "x",
    });
    expect(typeof (t as { execute?: unknown }).execute).toBe("function");
    expect((t as { description: string }).description).toBe("no-op");
  });
});

// ---------------------------------------------------------------------------
describe("synapseTool.execute instrumentation", () => {
  it("calls inner execute and emits INTENTION via intendWith", async () => {
    const innerExec = vi.fn(async (args: { path: string }) => ({
      bytes: args.path.length,
    }));
    const t = synapseTool({
      name: "write_file",
      execute: innerExec,
    });

    const result = await (
      t as { execute: (a: { path: string }) => Promise<{ bytes: number }> }
    ).execute({ path: "/tmp/foo.txt" });

    expect(intendWithMock).toHaveBeenCalledTimes(1);
    const callOpts = intendWithMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(callOpts["scope"]).toEqual(["repo.fs.tmp/foo.txt:w"]);
    expect(callOpts["agent"]).toBe("vercel_agent");
    expect(callOpts["expectedOutcome"]).toBe("vercel-ai:write_file");
    expect(callOpts["proposedAction"]).toEqual({
      tool: "write_file",
      args: { path: "/tmp/foo.txt" },
    });
    expect(innerExec).toHaveBeenCalledWith({ path: "/tmp/foo.txt" }, undefined);
    expect(result).toEqual({ bytes: 12 });
  });

  it("error in inner execute → markFailed + rethrow", async () => {
    const innerExec = vi.fn(async () => {
      throw new Error("disk full");
    });
    const t = synapseTool({
      name: "write_file",
      execute: innerExec,
    });

    let caught: Error | null = null;
    try {
      await (t as { execute: (a: unknown) => Promise<unknown> }).execute({
        path: "/tmp/x",
      });
    } catch (e) {
      caught = e as Error;
    }

    expect(caught).not.toBeNull();
    expect(caught?.message).toBe("disk full");
    expect(intendWithMock).toHaveBeenCalledTimes(1);
    expect(innerExec).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
describe("wrapVercelTools", () => {
  it("returns a wrapped map preserving keys", () => {
    const tools = {
      writeFile: {
        description: "fs",
        execute: vi.fn(async () => ({ ok: true })),
      },
      readFile: {
        description: "read",
        execute: vi.fn(async () => "content"),
      },
    };
    const wrapped = wrapVercelTools(tools);
    expect(Object.keys(wrapped).sort()).toEqual(["readFile", "writeFile"]);
    expect(typeof wrapped.writeFile.execute).toBe("function");
  });

  it("each wrapped tool dispatches via intendWith on call", async () => {
    const tools = {
      write_file: {
        execute: vi.fn(async (_a: unknown) => ({ ok: true })),
      },
    };
    const wrapped = wrapVercelTools(tools);
    await (
      wrapped.write_file.execute as (a: unknown) => Promise<unknown>
    )({ path: "out.log" });
    expect(intendWithMock).toHaveBeenCalledTimes(1);
    const opts = intendWithMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(opts["scope"]).toEqual(["repo.fs.out.log:w"]);
  });

  it("respects per-tool override skip flag", async () => {
    const tools = {
      writeFile: {
        execute: vi.fn(async () => "result"),
      },
    };
    const wrapped = wrapVercelTools(tools, {
      overrides: { writeFile: { skip: true } },
    });
    // Should be original (no instrumentation) — same execute fn reference
    expect(wrapped.writeFile.execute).toBe(tools.writeFile.execute);
  });
});

// ---------------------------------------------------------------------------
describe("scope inference", () => {
  it("filesystem path → repo.fs.<path>:w", () => {
    expect(inferVercelAIScope("write_file", { path: "src/x.ts" })).toEqual([
      "repo.fs.src/x.ts:w",
    ]);
    expect(inferVercelAIScope("edit_file", { file_path: "/etc/hosts" })).toEqual([
      "repo.fs.etc/hosts:w",
    ]);
  });

  it("shell name → repo.shell:w", () => {
    expect(inferVercelAIScope("bash", { cmd: "ls" })).toEqual(["repo.shell:w"]);
    expect(inferVercelAIScope("execute_code", {})).toEqual(["repo.shell:w"]);
  });

  it("HTTP write (POST) → http.<host>.post:w", () => {
    expect(
      inferVercelAIScope("fetch", {
        method: "POST",
        url: "https://api.example.com/v1/items",
      }),
    ).toEqual(["http.api.example.com.post:w"]);
  });

  it("HTTP GET → no scope (read)", () => {
    expect(
      inferVercelAIScope("fetch", { method: "GET", url: "https://api.x" }),
    ).toEqual([]);
  });

  it("read-shaped tool name → no scope", () => {
    expect(inferVercelAIScope("read_file", { path: "x.ts" })).toEqual([]);
    expect(inferVercelAIScope("search", { query: "foo" })).toEqual([]);
    expect(inferVercelAIScope("list_buckets", {})).toEqual([]);
  });

  it("browser_ tool with url", () => {
    expect(
      inferVercelAIScope("browser_click", { url: "https://x.com/login" }),
    ).toEqual(["repo.browser.https___x.com_login:w"]);
  });

  it("generic write fallback when name is mutating", () => {
    expect(inferVercelAIScope("send_email", { to: "x@y" })).toEqual([
      "tool.send_email:w",
    ]);
    expect(inferVercelAIScope("post_message", { id: "abc" })).toEqual([
      "tool.post_message.abc:w",
    ]);
  });
});

// ---------------------------------------------------------------------------
describe("override semantics", () => {
  it("explicit `scope` overrides inferred scope", async () => {
    const innerExec = vi.fn(async () => "ok");
    const t = synapseTool({
      name: "write_file",
      scope: ["custom.scope:w"],
      execute: innerExec,
    });
    await (t as { execute: (a: unknown) => Promise<unknown> }).execute({
      path: "/tmp/x",
    });
    const opts = intendWithMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(opts["scope"]).toEqual(["custom.scope:w"]);
  });

  it("explicit `agentId` overrides default", async () => {
    const innerExec = vi.fn(async () => "ok");
    const t = synapseTool({
      name: "write_file",
      agentId: "my_special_agent",
      execute: innerExec,
    });
    await (t as { execute: (a: unknown) => Promise<unknown> }).execute({
      path: "/tmp/y",
    });
    const opts = intendWithMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(opts["agent"]).toBe("my_special_agent");
  });

  it("read-shaped tool → no INTENTION emitted (intendWith never called)", async () => {
    const innerExec = vi.fn(async () => "content");
    const t = synapseTool({
      name: "read_file",
      execute: innerExec,
    });
    const result = await (
      t as { execute: (a: unknown) => Promise<unknown> }
    ).execute({ path: "/tmp/z" });
    expect(intendWithMock).not.toHaveBeenCalled();
    expect(innerExec).toHaveBeenCalled();
    expect(result).toBe("content");
  });

  it("install() default agentId flows into instrumented execute", async () => {
    install({ framework: "vercel-ai", agentId: "engineer", auto: false });
    const t = synapseTool({
      name: "write_file",
      execute: async () => "ok",
    });
    await (t as { execute: (a: unknown) => Promise<unknown> }).execute({
      path: "/etc/x",
    });
    const opts = intendWithMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(opts["agent"]).toBe("engineer");
  });
});

// ---------------------------------------------------------------------------
describe("registration + install integration", () => {
  it("framework is registered under all aliases", () => {
    expect(_FRAMEWORK_REGISTRY.has("vercel-ai")).toBe(true);
    expect(_FRAMEWORK_REGISTRY.has("vercel")).toBe(true);
    expect(_FRAMEWORK_REGISTRY.has("ai")).toBe(true);
  });

  it("install({framework:'vercel-ai'}) returns hooksInstalled with vercel-ai", () => {
    const r = install({ framework: "vercel-ai", auto: false });
    expect(r.framework).toBe("vercel-ai");
    expect(r.hooksInstalled).toEqual(["vercel-ai"]);
  });

  it("install({framework:'vercel'}) alias also wires up", () => {
    const r = install({ framework: "vercel", auto: false });
    expect(r.framework).toBe("vercel");
    expect(r.hooksInstalled).toEqual(["vercel"]);
  });

  it("getCallback() returns synapseTool factory", () => {
    expect(getVercelAICallback()).toBe(synapseTool);
  });
});
