/**
 * LangGraph.js / LangChain.js adapter for `synapse.install({ framework: "langgraph" })`.
 *
 * This module ships a `BaseCallbackHandler`-shaped class that bridges
 * LangChain.js tool-call events to `synapse.intend()`. The handler is
 * attached on the user's graph (or chain) via:
 *
 * ```ts
 *   import * as synapse from "synapse-protocol";
 *   synapse.install({ framework: "langgraph", sessionId: "demo" });
 *
 *   await graph.invoke(input, {
 *     callbacks: [synapse.frameworks.getCallback()],
 *   });
 * ```
 *
 * Why a callback? LangChain.js mirrors the Python `BaseCallbackHandler`
 * surface — `handleToolStart` / `handleToolEnd` / `handleToolError` —
 * and Node.js is single-threaded, so we don't have to worry about the
 * install-time loop pinning that the Python adapter does. Each callback
 * is `async` and just `await`s the `intend()` flow normally.
 *
 * Caveat: if a user runs LangGraph.js in `worker_threads` or
 * `child_process` workers, multi-process Synapse coordination still works
 * because the source of truth is the Redis bus — but each worker must
 * call `synapse.install()` itself. (This is the same constraint as every
 * other Synapse adapter.)
 */
import { intend, IntentionHandle } from "../intend.js";
import { registerFramework } from "../install.js";

// ---------------------------------------------------------------------------
// Identity / scope inference (mirrors sdk-python/synapse/frameworks/langgraph.py
// + sdk-python/synapse/audit/{events,scope_inference}.py).
// ---------------------------------------------------------------------------

const WRITE_KWS = [
  "write", "edit", "patch", "delete", "create", "update", "modify",
  "execute", "run", "send", "post", "publish", "deploy", "commit",
  "save", "insert", "upsert", "merge", "render", "generate",
];

const FS_WRITE_NAMES = new Set([
  "write_file", "write", "edit_file", "edit", "patch", "patch_file",
  "create_file", "delete_file", "fs.write", "fs.edit", "fs.delete",
  "files_create", "files_update", "str_replace_editor",
  "filesystem.write", "filesystem.edit",
]);

const SHELL_NAMES = new Set([
  "terminal", "shell", "bash", "sh", "subprocess", "execute_code",
  "run_command", "exec", "run", "process",
]);

function _sanitizePath(p: string): string {
  return p.replace(/[^a-zA-Z0-9._/-]/g, "_").replace(/^\/+/, "");
}

/**
 * Best-effort write classification. Read-only tools (e.g. `web_search`,
 * `read_file`, `list_dir`) return false so we skip Synapse INTENTION
 * emission entirely — they can't collide.
 */
export function isWriteTool(
  toolName: string,
  toolArgs: Record<string, unknown>,
): boolean {
  const lower = toolName.toLowerCase();
  if (WRITE_KWS.some((kw) => lower.includes(kw))) return true;
  // Shell / subprocess tools mutate state by definition.
  if (SHELL_NAMES.has(lower)) return true;
  // HTTP tools count as writes only when the method indicates mutation;
  // we surface this here so inferScope's HTTP rule can run.
  if (
    lower === "http_request" ||
    lower === "fetch" ||
    lower === "request" ||
    lower.startsWith("http.")
  ) {
    const method = String(toolArgs["method"] ?? "GET").toUpperCase();
    if (
      method === "POST" ||
      method === "PUT" ||
      method === "PATCH" ||
      method === "DELETE"
    ) {
      return true;
    }
  }
  if ("path" in toolArgs || "file_path" in toolArgs) {
    if (
      !lower.includes("read") &&
      !lower.includes("search") &&
      !lower.includes("list")
    ) {
      return true;
    }
  }
  return false;
}

/**
 * Map a tool call to a Synapse scope claim. Returns null if the tool is
 * read-only (no scope to claim).
 */
export function inferScope(
  toolName: string,
  toolArgs: Record<string, unknown>,
): string[] | null {
  if (!isWriteTool(toolName, toolArgs)) return null;

  const lower = toolName.toLowerCase();

  // Filesystem rule
  if (
    FS_WRITE_NAMES.has(lower) ||
    lower.endsWith(".write") ||
    lower.endsWith(".edit") ||
    lower.endsWith(".patch")
  ) {
    const path =
      (toolArgs["path"] as string | undefined) ??
      (toolArgs["file_path"] as string | undefined) ??
      (toolArgs["filename"] as string | undefined) ??
      (toolArgs["filepath"] as string | undefined);
    if (path) return [`repo.fs.${_sanitizePath(String(path))}:w`];
    return ["repo.fs.unknown:w"];
  }

  // Shell rule
  if (SHELL_NAMES.has(lower)) return ["repo.shell:w"];

  // HTTP-write rule
  if (
    lower === "http_request" ||
    lower === "fetch" ||
    lower === "request" ||
    lower.startsWith("http.")
  ) {
    const method = String(toolArgs["method"] ?? "GET").toUpperCase();
    const url =
      (toolArgs["url"] as string | undefined) ??
      (toolArgs["endpoint"] as string | undefined) ??
      "";
    if (
      (method === "POST" ||
        method === "PUT" ||
        method === "PATCH" ||
        method === "DELETE") &&
      url
    ) {
      // Strip query/fragment, sanitize host+path
      try {
        const u = new URL(url);
        // Preserve the leading slash on the pathname so the scope reads
        // like "http.<host>/<path>:w".
        const path = u.pathname.replace(/[^a-zA-Z0-9._/-]/g, "_");
        return [`http.${u.host}${path}:w`];
      } catch {
        return [`http.${_sanitizePath(url)}:w`];
      }
    }
    return null;
  }

  // Generic write — bucket under tool name
  const safe = toolName.replace(/[^a-zA-Z0-9._-]/g, "_");
  return [`tool.${safe}:w`];
}

/**
 * Resolve agent_id from LangChain metadata + tags, in priority order:
 *   1. metadata.agent_id
 *   2. metadata.langgraph_node
 *   3. metadata.agent_name
 *   4. metadata["graph.node.id"]
 *   5. first non-system tag
 *   6. "unknown_agent"
 */
export function agentIdFrom(
  metadata: Record<string, unknown> | undefined | null,
  tags: string[] | undefined | null,
): string {
  const md = metadata ?? {};
  for (const k of ["agent_id", "langgraph_node", "agent_name", "graph.node.id"]) {
    const v = md[k];
    if (v !== undefined && v !== null && String(v).length > 0) return String(v);
  }
  for (const t of tags ?? []) {
    if (
      typeof t === "string" &&
      t.length > 0 &&
      !t.startsWith("seq:") &&
      !t.startsWith("graph:")
    ) {
      return t;
    }
  }
  return "unknown_agent";
}

/**
 * Resolve session_id, in priority order:
 *   1. metadata.thread_id
 *   2. metadata.session_id
 *   3. metadata.conversation_id
 *   4. process.env.SYNAPSE_SESSION_ID
 *   5. String(runId) as last resort
 */
export function sessionIdFrom(
  metadata: Record<string, unknown> | undefined | null,
  runId: unknown,
  defaultSessionId?: string,
): string {
  if (defaultSessionId) return defaultSessionId;
  const md = metadata ?? {};
  for (const k of ["thread_id", "session_id", "conversation_id"]) {
    const v = md[k];
    if (v !== undefined && v !== null && String(v).length > 0) return String(v);
  }
  const env = process.env["SYNAPSE_SESSION_ID"];
  if (env && env.length > 0) return env;
  if (runId !== undefined && runId !== null) return String(runId);
  return "default_session";
}

// ---------------------------------------------------------------------------
// LangChain.js BaseCallbackHandler-shaped adapter.
// ---------------------------------------------------------------------------

/**
 * Structural type matching the slice of LangChain.js's `BaseCallbackHandler`
 * we care about. We don't import @langchain/core/* so the SDK works without
 * langchain.js installed.
 */
export interface BaseCallbackHandlerLike {
  name?: string;
  ignoreLLM?: boolean;
  ignoreChain?: boolean;
  handleToolStart(
    tool: { name?: string; id?: string[] } | Record<string, unknown> | undefined,
    input: string,
    runId: string,
    parentRunId?: string,
    tags?: string[],
    metadata?: Record<string, unknown>,
    runName?: string,
  ): Promise<void> | void;
  handleToolEnd(
    output: unknown,
    runId: string,
    parentRunId?: string,
    tags?: string[],
  ): Promise<void> | void;
  handleToolError(
    error: unknown,
    runId: string,
    parentRunId?: string,
    tags?: string[],
  ): Promise<void> | void;
}

function parseInput(input: unknown): Record<string, unknown> {
  if (input === null || input === undefined) return {};
  if (typeof input === "object") return input as Record<string, unknown>;
  if (typeof input === "string") {
    const s = input.trim();
    if (s.startsWith("{")) {
      try {
        const v = JSON.parse(s);
        if (v && typeof v === "object") return v as Record<string, unknown>;
      } catch {
        /* fall through */
      }
    }
    return { input: s };
  }
  return {};
}

function toolNameFrom(
  serialized: { name?: string; id?: string[] } | Record<string, unknown> | undefined,
  runName?: string,
): string {
  if (runName && runName.length > 0) return runName;
  if (serialized && typeof serialized === "object") {
    const s = serialized as { name?: string; id?: string[] };
    if (typeof s.name === "string" && s.name.length > 0) return s.name;
    if (Array.isArray(s.id) && s.id.length > 0) {
      return String(s.id[s.id.length - 1]);
    }
  }
  return "unknown_tool";
}

/**
 * Synapse callback for LangGraph.js / LangChain.js. Attach via
 * `graph.invoke(input, { callbacks: [callback] })`.
 *
 * Lifecycle:
 *   - `handleToolStart`: classify write/read; if write, build scope and
 *     call `intend()`. The resulting `IntentionHandle` is stashed
 *     keyed by `runId`.
 *   - `handleToolEnd`: pop the handle, set its state_diff to a small
 *     output preview, and call `dispose()` to emit RESOLUTION.
 *   - `handleToolError`: pop the handle, mark it failed, dispose.
 *
 * Read-only tools are skipped entirely (no INTENTION emitted) so search /
 * fetch / list calls don't fight for scope they can't conflict on.
 */
export class SynapseLangGraphCallback implements BaseCallbackHandlerLike {
  /** LangChain.js reads this for log lines / dedupe. */
  public name = "SynapseLangGraphCallback";
  public ignoreLLM = true;
  public ignoreChain = true;

  private readonly _defaultSessionId: string | undefined;
  private readonly _active: Map<string, IntentionHandle> = new Map();

  constructor(opts: { defaultSessionId?: string } = {}) {
    this._defaultSessionId = opts.defaultSessionId;
  }

  /** Inspectable map of in-flight intentions, keyed by LangChain runId. Test-only. */
  get _activeMap(): Map<string, IntentionHandle> {
    return this._active;
  }

  async handleToolStart(
    serialized:
      | { name?: string; id?: string[] }
      | Record<string, unknown>
      | undefined,
    input: string,
    runId: string,
    _parentRunId?: string,
    tags?: string[],
    metadata?: Record<string, unknown>,
    runName?: string,
  ): Promise<void> {
    try {
      const toolName = toolNameFrom(serialized, runName);
      const toolArgs = parseInput(input);

      const scope = inferScope(toolName, toolArgs);
      if (scope === null) {
        // Read-only — skip
        return;
      }

      const agentId = agentIdFrom(metadata, tags);
      const sessionId = sessionIdFrom(metadata, runId, this._defaultSessionId);

      const handle = await intend({
        scope,
        agent: agentId,
        session: sessionId,
        expectedOutcome: `langgraph:${toolName}`,
        proposedAction: { tool: toolName, args: toolArgs },
        blocking: true,
        gateMs: Number(process.env["SYNAPSE_GATE_MS"] ?? 50),
      });

      this._active.set(runId, handle);
    } catch (e) {
      // Best-effort — never let Synapse break the user's graph.
      // eslint-disable-next-line no-console
      console.warn("synapse.langgraph: handleToolStart failed", e);
    }
  }

  async handleToolEnd(output: unknown, runId: string): Promise<void> {
    const handle = this._active.get(runId);
    if (!handle) return;
    this._active.delete(runId);
    try {
      const preview =
        typeof output === "string"
          ? output.slice(0, 200)
          : JSON.stringify(output).slice(0, 200);
      handle.setStateDiff({ output_preview: preview });
    } catch {
      /* ignore preview errors */
    }
    try {
      await handle.dispose();
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn("synapse.langgraph: handleToolEnd dispose failed", e);
    }
  }

  async handleToolError(error: unknown, runId: string): Promise<void> {
    const handle = this._active.get(runId);
    if (!handle) return;
    this._active.delete(runId);
    const msg =
      error instanceof Error ? error.message : String(error ?? "tool error");
    handle.markFailed(msg);
    try {
      await handle.dispose();
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn("synapse.langgraph: handleToolError dispose failed", e);
    }
  }
}

// ---------------------------------------------------------------------------
// Singleton accessor + framework registration
// ---------------------------------------------------------------------------

let _handlerSingleton: SynapseLangGraphCallback | null = null;

/** Returns the install()-built callback singleton, or null if install hasn't run. */
export function getCallback(): SynapseLangGraphCallback | null {
  return _handlerSingleton;
}

/** Reset the singleton — used by tests. */
export function _resetCallback(): void {
  _handlerSingleton = null;
}

function installLangGraph(opts: Record<string, unknown>): void {
  // `install()` only forwards `frameworkOpts` to us, so prefer that. As a
  // fallback we read SYNAPSE_SESSION_ID — `install({ sessionId })` always
  // sets that env var, so this is the natural bridge from the top-level
  // option.
  const fromOpts = opts["sessionId"] ?? opts["session_id"];
  const fromEnv = process.env["SYNAPSE_SESSION_ID"];
  const candidate =
    typeof fromOpts === "string" && fromOpts.length > 0
      ? fromOpts
      : typeof fromEnv === "string" && fromEnv.length > 0
        ? fromEnv
        : undefined;
  _handlerSingleton = new SynapseLangGraphCallback({
    ...(candidate !== undefined ? { defaultSessionId: candidate } : {}),
  });
  // eslint-disable-next-line no-console
  console.log(
    "synapse.install(framework='langgraph'): callback ready. Attach via " +
      "graph.invoke(input, { callbacks: [synapse.frameworks.getCallback()] })",
  );
}

// Self-register under all the common aliases
registerFramework("langgraph", installLangGraph);
registerFramework("langchain", installLangGraph);
registerFramework("langchain.js", installLangGraph);
registerFramework("@langchain/langgraph", installLangGraph);
