/**
 * Unit tests for the LangGraph.js / LangChain.js callback adapter.
 *
 * We never import @langchain/core/* — the adapter is structurally typed,
 * so the tests run with no langchain.js dependency. The `intend()` flow
 * is exercised against the offline runtime (no Redis), so the callback
 * still records its in-flight handles even though the underlying
 * Synapse Agent is null.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  SynapseLangGraphCallback,
  agentIdFrom,
  getCallback,
  inferScope,
  isWriteTool,
  sessionIdFrom,
  _resetCallback,
} from "./langgraph.js";
import { install, _FRAMEWORK_REGISTRY, shutdown } from "../install.js";
import { _runtime } from "../intend.js";

const SAVED_ENV = { ...process.env };

beforeEach(async () => {
  await shutdown();
  delete process.env["SYNAPSE_REDIS_URL"];
  delete process.env["SYNAPSE_POSTGRES_DSN"];
  delete process.env["SYNAPSE_SESSION_ID"];
  _resetCallback();
});

afterEach(async () => {
  await shutdown();
  Object.assign(process.env, SAVED_ENV);
});

// ---------------------------------------------------------------------------
describe("isWriteTool", () => {
  it("classifies write keywords as writes", () => {
    expect(isWriteTool("write_file", {})).toBe(true);
    expect(isWriteTool("edit_file", {})).toBe(true);
    expect(isWriteTool("delete_record", {})).toBe(true);
    expect(isWriteTool("create_user", {})).toBe(true);
    expect(isWriteTool("update_doc", {})).toBe(true);
    expect(isWriteTool("send_email", {})).toBe(true);
  });

  it("classifies search/read tools as non-writes", () => {
    expect(isWriteTool("web_search", {})).toBe(false);
    expect(isWriteTool("read_file", { file_path: "/tmp/x" })).toBe(false);
    expect(isWriteTool("list_dir", {})).toBe(false);
    expect(isWriteTool("get_weather", {})).toBe(false);
  });

  it("treats path-bearing tools as writes by default", () => {
    expect(isWriteTool("touch", { path: "/tmp/x" })).toBe(true);
  });
});

// ---------------------------------------------------------------------------
describe("inferScope", () => {
  it("returns null for read-only tools", () => {
    expect(inferScope("web_search", { query: "synapse" })).toBeNull();
    expect(inferScope("read_file", { file_path: "/etc/hosts" })).toBeNull();
  });

  it("returns repo.fs.<path>:w for filesystem writes", () => {
    expect(inferScope("write_file", { path: "src/foo.ts" })).toEqual([
      "repo.fs.src/foo.ts:w",
    ]);
    expect(inferScope("edit_file", { file_path: "/abs/path.py" })).toEqual([
      "repo.fs.abs/path.py:w",
    ]);
  });

  it("returns repo.shell:w for shell tools", () => {
    expect(inferScope("bash", { cmd: "ls" })).toEqual(["repo.shell:w"]);
    expect(inferScope("subprocess", {})).toEqual(["repo.shell:w"]);
  });

  it("returns null for HTTP GET, scope for HTTP POST", () => {
    expect(
      inferScope("http_request", { method: "GET", url: "https://x" }),
    ).toBeNull();
    expect(
      inferScope("http_request", {
        method: "POST",
        url: "https://api.example.com/v1/items",
      }),
    ).toEqual(["http.api.example.com/v1/items:w"]);
  });

  it("falls back to tool.<name>:w for unknown writes", () => {
    expect(inferScope("publish_message", { topic: "t" })).toEqual([
      "tool.publish_message:w",
    ]);
  });
});

// ---------------------------------------------------------------------------
describe("agentIdFrom resolution order", () => {
  it("metadata.agent_id wins over everything", () => {
    expect(
      agentIdFrom(
        {
          agent_id: "a-explicit",
          langgraph_node: "node-x",
          agent_name: "name-x",
          "graph.node.id": "gnode",
        },
        ["t1"],
      ),
    ).toBe("a-explicit");
  });

  it("metadata.langgraph_node wins over agent_name", () => {
    expect(
      agentIdFrom({ langgraph_node: "node-x", agent_name: "name-x" }, []),
    ).toBe("node-x");
  });

  it("metadata.agent_name wins over graph.node.id", () => {
    expect(
      agentIdFrom({ agent_name: "name-x", "graph.node.id": "gnode" }, []),
    ).toBe("name-x");
  });

  it("falls through to first non-system tag", () => {
    expect(agentIdFrom({}, ["seq:abc", "graph:xyz", "real-agent"])).toBe(
      "real-agent",
    );
  });

  it("returns 'unknown_agent' when nothing usable", () => {
    expect(agentIdFrom({}, ["seq:abc", "graph:xyz"])).toBe("unknown_agent");
    expect(agentIdFrom(null, null)).toBe("unknown_agent");
  });
});

// ---------------------------------------------------------------------------
describe("sessionIdFrom resolution order", () => {
  it("explicit defaultSessionId wins", () => {
    expect(
      sessionIdFrom({ thread_id: "tid", session_id: "sid" }, "rid", "DEFAULT"),
    ).toBe("DEFAULT");
  });

  it("metadata.thread_id wins over session_id", () => {
    expect(
      sessionIdFrom({ thread_id: "tid", session_id: "sid" }, "rid"),
    ).toBe("tid");
  });

  it("metadata.session_id wins over conversation_id", () => {
    expect(
      sessionIdFrom({ session_id: "sid", conversation_id: "cid" }, "rid"),
    ).toBe("sid");
  });

  it("falls back to env, then runId, then default_session", () => {
    process.env["SYNAPSE_SESSION_ID"] = "env-sid";
    expect(sessionIdFrom({}, "rid")).toBe("env-sid");
    delete process.env["SYNAPSE_SESSION_ID"];
    expect(sessionIdFrom({}, "rid")).toBe("rid");
    expect(sessionIdFrom({}, undefined as unknown as string)).toBe(
      "default_session",
    );
  });
});

// ---------------------------------------------------------------------------
describe("SynapseLangGraphCallback lifecycle", () => {
  it("is instantiable; its hook methods are async and don't throw", async () => {
    const cb = new SynapseLangGraphCallback();
    expect(typeof cb.handleToolStart).toBe("function");
    expect(typeof cb.handleToolEnd).toBe("function");
    expect(typeof cb.handleToolError).toBe("function");
    // No-op call should resolve cleanly (read-only tool, skipped)
    await cb.handleToolStart(
      { name: "web_search" },
      JSON.stringify({ query: "x" }),
      "run-1",
    );
    expect(cb._activeMap.size).toBe(0);
  });

  it("read-only tool does NOT register an in-flight intention", async () => {
    const cb = new SynapseLangGraphCallback();
    await cb.handleToolStart(
      { name: "web_search" },
      JSON.stringify({ query: "synapse" }),
      "run-read-1",
    );
    expect(cb._activeMap.has("run-read-1")).toBe(false);
  });

  it("write tool DOES register an in-flight intention", async () => {
    const cb = new SynapseLangGraphCallback();
    await cb.handleToolStart(
      { name: "write_file" },
      JSON.stringify({ path: "src/foo.ts", content: "..." }),
      "run-write-1",
      undefined,
      ["my-agent"],
      { thread_id: "T-1" },
    );
    expect(cb._activeMap.has("run-write-1")).toBe(true);
    const handle = cb._activeMap.get("run-write-1")!;
    expect(handle.scope).toEqual(["repo.fs.src/foo.ts:w"]);
    expect(handle.agentId).toBe("my-agent");
    expect(handle.sessionId).toBe("T-1");
    // Cleanup
    await cb.handleToolEnd("ok", "run-write-1");
    expect(cb._activeMap.has("run-write-1")).toBe(false);
  });

  it("handleToolEnd disposes the stashed handle and sets state_diff", async () => {
    const cb = new SynapseLangGraphCallback();
    await cb.handleToolStart(
      { name: "write_file" },
      JSON.stringify({ path: "x.ts" }),
      "run-end-1",
    );
    const handle = cb._activeMap.get("run-end-1")!;
    expect(handle).toBeDefined();
    await cb.handleToolEnd("hello world", "run-end-1");
    expect(cb._activeMap.has("run-end-1")).toBe(false);
    expect(handle.stateDiff["output_preview"]).toBe("hello world");
    expect(handle.outcome).toBe("success");
  });

  it("handleToolError marks the handle failed and disposes", async () => {
    const cb = new SynapseLangGraphCallback();
    await cb.handleToolStart(
      { name: "write_file" },
      JSON.stringify({ path: "x.ts" }),
      "run-err-1",
    );
    const handle = cb._activeMap.get("run-err-1")!;
    await cb.handleToolError(new Error("boom"), "run-err-1");
    expect(cb._activeMap.has("run-err-1")).toBe(false);
    expect(handle.outcome).toBe("failure");
    expect(handle.errorMessage).toBe("boom");
  });

  it("handleToolEnd on unknown runId is a safe no-op", async () => {
    const cb = new SynapseLangGraphCallback();
    await expect(
      cb.handleToolEnd("anything", "no-such-run"),
    ).resolves.toBeUndefined();
  });

  it("handleToolError on unknown runId is a safe no-op", async () => {
    const cb = new SynapseLangGraphCallback();
    await expect(
      cb.handleToolError(new Error("e"), "no-such-run"),
    ).resolves.toBeUndefined();
  });

  it("uses the install-time defaultSessionId when set", async () => {
    const cb = new SynapseLangGraphCallback({ defaultSessionId: "INSTALLED" });
    await cb.handleToolStart(
      { name: "write_file" },
      JSON.stringify({ path: "y.ts" }),
      "run-default-sid",
      undefined,
      [],
      { thread_id: "WOULDLOSE" },
    );
    const handle = cb._activeMap.get("run-default-sid")!;
    expect(handle.sessionId).toBe("INSTALLED");
    await cb.handleToolEnd(null, "run-default-sid");
  });

  it("parses raw-string input as plain object when not JSON", async () => {
    const cb = new SynapseLangGraphCallback();
    // Use a write keyword so we go through the intend path
    await cb.handleToolStart(
      { name: "publish_message" },
      "just a string, not JSON",
      "run-rawstr",
    );
    const handle = cb._activeMap.get("run-rawstr")!;
    expect(handle).toBeDefined();
    expect(handle.scope).toEqual(["tool.publish_message:w"]);
    await cb.handleToolEnd("ok", "run-rawstr");
  });
});

// ---------------------------------------------------------------------------
describe("install({framework: 'langgraph'}) dispatch", () => {
  it("registers the langgraph alias and builds a singleton callback", () => {
    expect(_FRAMEWORK_REGISTRY.has("langgraph")).toBe(true);
    expect(_FRAMEWORK_REGISTRY.has("langchain")).toBe(true);
    expect(_FRAMEWORK_REGISTRY.has("langchain.js")).toBe(true);

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const r = install({ framework: "langgraph", auto: false });
    expect(r.framework).toBe("langgraph");
    expect(r.hooksInstalled).toEqual(["langgraph"]);
    const cb = getCallback();
    expect(cb).toBeInstanceOf(SynapseLangGraphCallback);
    logSpy.mockRestore();
  });

  it("session_id from install() flows into the callback as defaultSessionId", async () => {
    install({ framework: "langgraph", sessionId: "S-FROM-INSTALL", auto: false });
    const cb = getCallback();
    expect(cb).not.toBeNull();
    await cb!.handleToolStart(
      { name: "write_file" },
      JSON.stringify({ path: "z.ts" }),
      "run-from-install",
      undefined,
      [],
      // Even though metadata supplies thread_id, the install-time default wins
      { thread_id: "WOULDLOSE" },
    );
    const handle = cb!._activeMap.get("run-from-install")!;
    expect(handle.sessionId).toBe("S-FROM-INSTALL");
    await cb!.handleToolEnd(null, "run-from-install");
  });

  it("install({framework: 'langchain'}) routes to the same installer", () => {
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const r = install({ framework: "langchain", auto: false });
    expect(r.hooksInstalled).toEqual(["langchain"]);
    expect(getCallback()).toBeInstanceOf(SynapseLangGraphCallback);
    logSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
describe("offline-mode integration", () => {
  it("offline runtime: handleToolStart still records a handle (no agent)", async () => {
    const cb = new SynapseLangGraphCallback();
    await cb.handleToolStart(
      { name: "write_file" },
      JSON.stringify({ path: "off.ts" }),
      "run-offline",
    );
    expect(_runtime.mode).toBe("offline");
    const handle = cb._activeMap.get("run-offline")!;
    expect(handle).toBeDefined();
    // intentionId stays empty in offline mode (no Agent)
    expect(handle.intentionId).toBe("");
    await cb.handleToolEnd("done", "run-offline");
    expect(handle.outcome).toBe("success");
  });
});
