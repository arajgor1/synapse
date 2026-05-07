/**
 * Unit tests for synapse.install / registerFramework / runtime defaults.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  _FRAMEWORK_REGISTRY,
  install,
  registerFramework,
  shutdown,
} from "./install.js";
import { _runtime } from "./intend.js";
import { MergePolicy } from "./policies/base.js";

const SAVED_ENV = { ...process.env };

beforeEach(async () => {
  await shutdown();
  _FRAMEWORK_REGISTRY.clear();
  delete process.env["SYNAPSE_REDIS_URL"];
  delete process.env["SYNAPSE_POSTGRES_DSN"];
  delete process.env["SYNAPSE_SESSION_ID"];
  delete process.env["SYNAPSE_DEFAULT_AGENT_ID"];
});

afterEach(async () => {
  await shutdown();
  _FRAMEWORK_REGISTRY.clear();
  Object.assign(process.env, SAVED_ENV);
});

// ---------------------------------------------------------------------------
describe("install() basics", () => {
  it("returns offline mode when no busUrl", () => {
    const r = install();
    expect(r.mode).toBe("offline");
    expect(r.busUrl).toBeUndefined();
    expect(r.hooksInstalled).toEqual([]);
  });

  it("propagates explicit busUrl into the runtime", () => {
    const r = install({ busUrl: "redis://x:6379/0", auto: false });
    expect(r.mode).toBe("live");
    expect(r.busUrl).toBe("redis://x:6379/0");
  });

  it("sets SYNAPSE_SESSION_ID env var if not already set", () => {
    install({ sessionId: "sess-99" });
    expect(process.env["SYNAPSE_SESSION_ID"]).toBe("sess-99");
  });

  it("does not overwrite existing SYNAPSE_SESSION_ID", () => {
    process.env["SYNAPSE_SESSION_ID"] = "preexisting";
    install({ sessionId: "shouldnotwin" });
    expect(process.env["SYNAPSE_SESSION_ID"]).toBe("preexisting");
  });

  it("sets SYNAPSE_DEFAULT_AGENT_ID env var if not already set", () => {
    install({ agentId: "agent-XX" });
    expect(process.env["SYNAPSE_DEFAULT_AGENT_ID"]).toBe("agent-XX");
  });
});

// ---------------------------------------------------------------------------
describe("install() policy plumbing", () => {
  it("merge_policy as a MergePolicy instance is stored on runtime", () => {
    const r = install({ mergePolicy: MergePolicy.redirect, auto: false });
    expect(r.mergePolicy).toBe("redirect");
    expect(_runtime.policy_defaults?.merge_policy).toBe(MergePolicy.redirect);
  });

  it("merge_policy as a string is resolved via policies registry", () => {
    const r = install({ mergePolicy: "abort", auto: false });
    expect(r.mergePolicy).toBe("abort");
    expect(_runtime.policy_defaults?.merge_policy).toBe(MergePolicy.abort);
  });

  it("critical_scopes are normalized + stored on runtime", () => {
    const r = install({
      criticalScopes: ["billing.*", "  prod.deploy.*  ", ""],
      auto: false,
    });
    expect(r.criticalScopes).toEqual(["billing.*", "prod.deploy.*"]);
    expect(_runtime.policy_defaults?.critical_scopes).toEqual([
      "billing.*",
      "prod.deploy.*",
    ]);
  });

  it("emit_beliefs_from_tool_results=true plumbed through", () => {
    const r = install({ emitBeliefsFromToolResults: true, auto: false });
    expect(r.emitBeliefsFromToolResults).toBe(true);
    expect(_runtime.policy_defaults?.emit_beliefs_from_tool_results).toBe(true);
  });

  it("emit_beliefs_from_tool_results=false (default) → false", () => {
    const r = install({ auto: false });
    expect(r.emitBeliefsFromToolResults).toBe(false);
  });
});

// ---------------------------------------------------------------------------
describe("registerFramework()", () => {
  it("registered fn is invoked when install({framework:name}) runs", () => {
    const fn = vi.fn();
    registerFramework("my-fw", fn);
    const r = install({ framework: "my-fw", frameworkOpts: { foo: 1 } });
    expect(fn).toHaveBeenCalledTimes(1);
    expect(fn).toHaveBeenCalledWith({ foo: 1 });
    expect(r.framework).toBe("my-fw");
    expect(r.hooksInstalled).toEqual(["my-fw"]);
  });

  it("install warns when framework is unknown", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const r = install({ framework: "nosuch-fw", auto: false });
    expect(r.framework).toBe("nosuch-fw");
    expect(r.hooksInstalled).toEqual([]);
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it("multiple registrations keyed by name", () => {
    const a = vi.fn();
    const b = vi.fn();
    registerFramework("a-fw", a);
    registerFramework("b-fw", b);
    install({ framework: "a-fw" });
    install({ framework: "b-fw" });
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
  });

  it("install fn that throws is caught and warned (doesn't break install)", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    registerFramework("bad-fw", () => {
      throw new Error("fw exploded");
    });
    const r = install({ framework: "bad-fw" });
    expect(r.hooksInstalled).toEqual([]);
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
describe("install() + intend() integration", () => {
  it("policy defaults from install() are picked up by intend()", async () => {
    const { intend } = await import("./intend.js");
    install({
      mergePolicy: MergePolicy.redirect,
      criticalScopes: ["secret.*"],
      auto: false,
    });
    const h = await intend({ scope: [], agent: "a" });
    expect(_runtime.policy_defaults?.merge_policy).toBe(MergePolicy.redirect);
    expect(_runtime.policy_defaults?.critical_scopes).toEqual(["secret.*"]);
    await h.dispose();
  });

  it("install() then shutdown() leaves runtime empty", async () => {
    install({ busUrl: "redis://x:6379/0", auto: false });
    expect(_runtime.mode).toBe("live");
    await shutdown();
    expect(_runtime.mode).toBeUndefined();
    expect(_runtime.bus).toBeUndefined();
    expect(_runtime.policy_defaults).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
describe("install() return shape", () => {
  it("returns expected fields", () => {
    const r = install({ auto: false });
    expect(Object.keys(r).sort()).toEqual(
      [
        "busUrl",
        "criticalScopes",
        "emitBeliefsFromToolResults",
        "framework",
        "hooksInstalled",
        "mergePolicy",
        "mode",
        "stateDsn",
      ].sort(),
    );
  });
});
