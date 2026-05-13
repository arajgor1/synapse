/**
 * Vercel AI SDK adapter for Synapse.
 *
 * The Vercel AI SDK (`ai` package) is the dominant TypeScript multi-agent +
 * LLM framework. Tools are defined via the `tool({ description, parameters,
 * execute })` factory and dispatched by `generateText` / `streamText`. The
 * `execute` callback is the single point where each tool actually fires —
 * that's the hook point.
 *
 * Because ESM modules cannot be safely monkey-patched, this adapter does NOT
 * try to mutate the user's `ai` import. Instead it ships a `synapseTool`
 * factory that wraps `tool()` and instruments `execute()` with
 * `synapse.intendWith(...)`. The user changes one import line:
 *
 * ```ts
 * import { synapseTool as tool } from "synapse-protocol/frameworks/vercel-ai";
 * import { z } from "zod";
 *
 * const writeFile = tool({
 *   description: "Write a file",
 *   parameters: z.object({ path: z.string(), content: z.string() }),
 *   execute: async ({ path, content }) => {
 *     await fs.writeFile(path, content);
 *     return { ok: true };
 *   },
 * });
 * ```
 *
 * Every invocation of the wrapped tool now emits INTENTION/RESOLUTION via
 * Synapse with an inferred or explicit scope. `wrapVercelTools(map)` converts
 * an existing tool map without per-tool code changes.
 */
import { intendWith, type IntentionHandle } from "../intend.js";
import { registerFramework } from "../install.js";

// ---------------------------------------------------------------------------
// Vercel AI SDK shape — replicated structurally so we don't take a hard
// dependency on the `ai` package. Users bring their own `tool()` import (or
// rely on synapseTool's drop-in replacement).
// ---------------------------------------------------------------------------
export type VercelToolExecute<TArgs = unknown, TResult = unknown> = (
  args: TArgs,
  opts?: unknown,
) => Promise<TResult> | TResult;

export interface VercelToolConfig<TArgs = unknown, TResult = unknown> {
  description?: string;
  parameters?: unknown; // typically a zod schema
  execute?: VercelToolExecute<TArgs, TResult>;
  // Vercel allows passing through extra fields (e.g. `experimental_*`).
  [key: string]: unknown;
}

/** A Vercel AI SDK tool object — opaque shape that gets handed to
 * `generateText({ tools })`. Structurally compatible with `ReturnType<tool>`. */
export type VercelTool<TArgs = unknown, TResult = unknown> = VercelToolConfig<
  TArgs,
  TResult
>;

// ---------------------------------------------------------------------------
// Synapse-extended config — adds optional Synapse coordination hints.
// ---------------------------------------------------------------------------
export interface SynapseToolExtras {
  /** Tool name; used in INTENTION + scope inference. Inferred from key in
   * `wrapVercelTools` if omitted. */
  name?: string;
  /** Explicit Synapse scope strings. Overrides inference entirely. */
  scope?: string[];
  /** Override the default agent id for THIS tool. */
  agentId?: string;
  /** Skip Synapse instrumentation for this tool. */
  skip?: boolean;
}

export type SynapseToolConfig<TArgs = unknown, TResult = unknown> =
  VercelToolConfig<TArgs, TResult> & SynapseToolExtras;

// ---------------------------------------------------------------------------
// Module-level defaults — set by install({ framework: "vercel-ai" }).
// ---------------------------------------------------------------------------
interface VercelAIDefaults {
  agentId: string;
  toolFactory?: <T extends VercelToolConfig<unknown, unknown>>(
    config: T,
  ) => VercelTool;
}

const _defaults: VercelAIDefaults = {
  agentId: "vercel_agent",
};

/** Internal — exposed for tests to reset state between cases. */
export function _resetVercelAIDefaults(): void {
  _defaults.agentId = "vercel_agent";
  delete _defaults.toolFactory;
  _cachedFactory = undefined;
}

// ---------------------------------------------------------------------------
// Scope inference — TS port of sdk-python/synapse/audit/scope_inference.py.
// Same vocabulary so audit results match a live runtime.
// ---------------------------------------------------------------------------
const SAFE_PATH_RE = /[^a-zA-Z0-9._/-]/g;
const SAFE_HOST_RE = /[^a-zA-Z0-9.-]/g;
const SAFE_GENERIC_RE = /[^a-zA-Z0-9._/-]/g;

function _sanitizePath(p: string): string {
  return p.replace(SAFE_PATH_RE, "_").replace(/^\/+/, "");
}

const FS_WRITE_NAMES = new Set([
  "write_file",
  "write",
  "edit_file",
  "edit",
  "patch",
  "patch_file",
  "create_file",
  "delete_file",
  "fs.write",
  "fs.edit",
  "fs.delete",
  "files_create",
  "files_update",
  "str_replace_editor",
  "filesystem.write",
  "filesystem.edit",
]);

const SHELL_NAMES = new Set([
  "terminal",
  "shell",
  "bash",
  "sh",
  "subprocess",
  "execute_code",
  "run_command",
  "exec",
  "run",
  "process",
]);

const HTTP_NAMES = new Set(["http_request", "fetch", "request"]);

const READ_KEYWORDS = ["read", "search", "list", "get", "fetch", "find", "view"];
const WRITE_KEYWORDS = [
  "write",
  "edit",
  "create",
  "update",
  "delete",
  "send",
  "post",
  "publish",
  "patch",
];

/**
 * Infer Synapse scope strings for a tool dispatch. Returns `[]` if the call
 * looks read-only (no INTENTION needed).
 */
export function inferScope(
  toolName: string,
  args: Record<string, unknown>,
): string[] {
  const name = toolName.toLowerCase();

  // Filesystem writes
  if (
    FS_WRITE_NAMES.has(name) ||
    name.endsWith(".write") ||
    name.endsWith(".edit") ||
    name.endsWith(".patch")
  ) {
    const path =
      (args["path"] as string | undefined) ??
      (args["file_path"] as string | undefined) ??
      (args["filename"] as string | undefined) ??
      (args["filepath"] as string | undefined);
    if (path) return [`repo.fs.${_sanitizePath(String(path))}:w`];
    return [`repo.fs.unknown:w`];
  }

  // Shell / subprocess
  if (SHELL_NAMES.has(name)) {
    return ["repo.shell:w"];
  }

  // HTTP — only writes count
  if (HTTP_NAMES.has(name) || name.startsWith("http.")) {
    const method = String(args["method"] ?? "GET").toUpperCase();
    const url = String(args["url"] ?? args["endpoint"] ?? "");
    if (
      (method === "POST" ||
        method === "PUT" ||
        method === "PATCH" ||
        method === "DELETE") &&
      url
    ) {
      const host =
        url.replace(/^https?:\/\//, "").split("/")[0] ?? "unknown";
      const hostSafe = host.replace(SAFE_HOST_RE, "_") || "unknown";
      return [`http.${hostSafe}.${method.toLowerCase()}:w`];
    }
    // GET / read-shaped → no INTENTION
    return [];
  }

  // DB writes
  if (
    name === "sql_execute" ||
    name === "execute_sql" ||
    name.startsWith("db.") ||
    name.startsWith("sql.") ||
    name === "query_database" ||
    name === "run_query"
  ) {
    const sql = String(args["query"] ?? args["sql"] ?? "");
    const m = sql.match(
      /(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+([a-zA-Z_][a-zA-Z0-9_]*)/i,
    );
    if (m && m[1]) return [`db.${m[1].toLowerCase()}:w`];
    return ["db.unknown:w"];
  }

  // Browser tools — selector or url
  if (name.startsWith("browser_") || name.startsWith("browser.")) {
    const target = String(
      args["url"] ?? args["selector"] ?? name,
    );
    const safe = target.replace(/[^a-zA-Z0-9._-]/g, "_").slice(0, 60);
    return [`repo.browser.${safe}:w`];
  }

  // Read-shaped names — explicit no-op so the call isn't double-instrumented.
  // Only treat as read if there's no write keyword AND there's a read keyword.
  const hasWriteKw = WRITE_KEYWORDS.some((kw) => name.includes(kw));
  const hasReadKw = READ_KEYWORDS.some((kw) => name.includes(kw));
  if (hasReadKw && !hasWriteKw) {
    return [];
  }

  // Generic write fallback — name suggests mutation
  if (hasWriteKw) {
    for (const k of [
      "path",
      "file_path",
      "filename",
      "filepath",
      "url",
      "endpoint",
      "key",
      "id",
    ]) {
      if (k in args) {
        const v = String(args[k] ?? "")
          .replace(SAFE_GENERIC_RE, "_")
          .slice(0, 80);
        return [`tool.${name}.${v}:w`];
      }
    }
    return [`tool.${name}:w`];
  }

  // Unknown — emit a defensive scope so coordination still works.
  return [`tool.${name}:w`];
}

// ---------------------------------------------------------------------------
// Lazy access to `ai`'s `tool()` factory.
//
// Vercel's `tool({...})` is essentially `(config) => config` with type
// magic — it returns its input as a tagged tool object. We try to import
// `ai` at call time; if it's unavailable (e.g. tests), we pass through the
// config as-is, which is structurally compatible.
// ---------------------------------------------------------------------------
type ToolFactoryFn = <T extends VercelToolConfig<unknown, unknown>>(
  config: T,
) => VercelTool;

let _cachedFactory: ToolFactoryFn | undefined;

async function _loadFactoryAsync(): Promise<ToolFactoryFn> {
  if (_cachedFactory) return _cachedFactory;
  if (_defaults.toolFactory) {
    _cachedFactory = _defaults.toolFactory as ToolFactoryFn;
    return _cachedFactory;
  }
  try {
    const mod = (await import("ai" as string).catch(() => null)) as
      | { tool?: ToolFactoryFn }
      | null;
    if (mod && typeof mod.tool === "function") {
      _cachedFactory = mod.tool;
      return _cachedFactory;
    }
  } catch {
    /* swallow */
  }
  // Fallback: identity. The Vercel AI SDK runtime is structural.
  _cachedFactory = ((config) => config) as ToolFactoryFn;
  return _cachedFactory;
}

function _loadFactorySync(): ToolFactoryFn {
  if (_cachedFactory) return _cachedFactory;
  if (_defaults.toolFactory) {
    _cachedFactory = _defaults.toolFactory as ToolFactoryFn;
    return _cachedFactory;
  }
  // Sync identity fallback. Most Vercel AI usage is fine with this — the
  // `tool` factory in `ai` is essentially identity + type tagging.
  _cachedFactory = ((config) => config) as ToolFactoryFn;
  return _cachedFactory;
}

/** Test/installer hook: inject a custom `tool()` factory (e.g. a vi mock). */
export function _setToolFactory(fn: ToolFactoryFn | undefined): void {
  if (fn === undefined) {
    delete _defaults.toolFactory;
    _cachedFactory = undefined;
  } else {
    _defaults.toolFactory = fn;
    _cachedFactory = fn;
  }
}

// ---------------------------------------------------------------------------
// synapseTool — the public drop-in replacement for `ai`'s `tool()`.
// ---------------------------------------------------------------------------

function _resolveAgentId(extras: SynapseToolExtras): string {
  return (
    extras.agentId ??
    process.env["SYNAPSE_DEFAULT_AGENT_ID"] ??
    _defaults.agentId
  );
}

function _resolveScope(
  extras: SynapseToolExtras,
  toolName: string,
  args: Record<string, unknown>,
): string[] {
  if (extras.scope !== undefined) return extras.scope;
  return inferScope(toolName, args);
}

function _instrumentExecute<TArgs, TResult>(
  toolName: string,
  extras: SynapseToolExtras,
  inner: VercelToolExecute<TArgs, TResult>,
): VercelToolExecute<TArgs, TResult> {
  return async (args: TArgs, opts?: unknown): Promise<TResult> => {
    const argsObj =
      args && typeof args === "object" ? (args as Record<string, unknown>) : {};
    const scope = _resolveScope(extras, toolName, argsObj);
    const agentId = _resolveAgentId(extras);

    // No scope → not a write. Pass through cleanly with no overhead.
    if (scope.length === 0) {
      return inner(args, opts);
    }

    return intendWith(
      {
        scope,
        agent: agentId,
        expectedOutcome: `vercel-ai:${toolName}`,
        proposedAction: { tool: toolName, args: argsObj },
      },
      async (handle: IntentionHandle): Promise<TResult> => {
        try {
          const result = await inner(args, opts);
          // Capture a small preview of the result to enrich RESOLUTION.
          let preview: unknown = result;
          if (typeof result === "string") {
            preview = result.slice(0, 200);
          } else {
            try {
              preview = JSON.stringify(result).slice(0, 200);
            } catch {
              preview = String(result).slice(0, 200);
            }
          }
          handle.setStateDiff({ output_preview: preview });
          return result;
        } catch (e) {
          handle.markFailed((e as Error)?.message ?? String(e));
          throw e;
        }
      },
    );
  };
}

/**
 * Drop-in replacement for `ai`'s `tool()` factory. Wraps `execute()` with
 * Synapse `intendWith(...)` so every invocation emits INTENTION + RESOLUTION
 * with an inferred (or explicit) scope.
 *
 * @example
 * ```ts
 * import { synapseTool as tool } from "synapse-protocol/frameworks/vercel-ai";
 * const writeFile = tool({
 *   name: "write_file",
 *   description: "Write a file",
 *   parameters: z.object({ path: z.string(), content: z.string() }),
 *   execute: async ({ path, content }) => fs.writeFile(path, content),
 * });
 * ```
 */
export function synapseTool<TArgs = unknown, TResult = unknown>(
  config: SynapseToolConfig<TArgs, TResult>,
): VercelTool<TArgs, TResult> {
  const factory = _loadFactorySync();
  const { name, scope, agentId, skip, execute, ...rest } = config;
  const extras: SynapseToolExtras = {};
  if (name !== undefined) extras.name = name;
  if (scope !== undefined) extras.scope = scope;
  if (agentId !== undefined) extras.agentId = agentId;
  if (skip !== undefined) extras.skip = skip;

  const toolName = name ?? (rest["description"] as string | undefined) ?? "tool";

  let wrappedExecute: VercelToolExecute<TArgs, TResult> | undefined = execute;
  if (execute && !skip) {
    wrappedExecute = _instrumentExecute(toolName, extras, execute);
  }

  const next: VercelToolConfig<TArgs, TResult> = { ...rest };
  if (wrappedExecute !== undefined) next.execute = wrappedExecute;
  return factory(next as unknown as VercelToolConfig<unknown, unknown>) as VercelTool<
    TArgs,
    TResult
  >;
}

/**
 * Async-aware variant — uses dynamic import of `ai` if available so the real
 * `tool()` factory tags the result. Prefer this when you have the option.
 */
export async function synapseToolAsync<TArgs = unknown, TResult = unknown>(
  config: SynapseToolConfig<TArgs, TResult>,
): Promise<VercelTool<TArgs, TResult>> {
  const factory = await _loadFactoryAsync();
  const { name, scope, agentId, skip, execute, ...rest } = config;
  const extras: SynapseToolExtras = {};
  if (name !== undefined) extras.name = name;
  if (scope !== undefined) extras.scope = scope;
  if (agentId !== undefined) extras.agentId = agentId;
  if (skip !== undefined) extras.skip = skip;

  const toolName = name ?? (rest["description"] as string | undefined) ?? "tool";

  let wrappedExecute: VercelToolExecute<TArgs, TResult> | undefined = execute;
  if (execute && !skip) {
    wrappedExecute = _instrumentExecute(toolName, extras, execute);
  }

  const next: VercelToolConfig<TArgs, TResult> = { ...rest };
  if (wrappedExecute !== undefined) next.execute = wrappedExecute;
  return factory(next as unknown as VercelToolConfig<unknown, unknown>) as VercelTool<
    TArgs,
    TResult
  >;
}

// ---------------------------------------------------------------------------
// wrapVercelTools — bulk helper for an existing tool map.
// ---------------------------------------------------------------------------

export interface WrapVercelToolsOptions {
  /** Default agent id for tools in this map (overrides install-time default). */
  agentId?: string;
  /** Per-tool overrides keyed by tool name. */
  overrides?: Record<string, SynapseToolExtras>;
}

/**
 * Wrap an existing `{ toolName: tool({...}) }` map so each entry's `execute()`
 * is Synapse-instrumented. The tool's own `name` (if set) takes precedence
 * over the map key for scope inference.
 *
 * @example
 * ```ts
 * import { wrapVercelTools } from "synapse-protocol/frameworks/vercel-ai";
 * const tools = wrapVercelTools({ writeFile, readFile, runShell });
 * await generateText({ model, tools });
 * ```
 */
export function wrapVercelTools<
  T extends Record<string, VercelToolConfig<unknown, unknown>>,
>(tools: T, opts: WrapVercelToolsOptions = {}): T {
  const out: Record<string, VercelToolConfig<unknown, unknown>> = {};
  for (const key of Object.keys(tools)) {
    const t = tools[key];
    if (!t) continue;

    const override = opts.overrides?.[key] ?? {};
    const explicitName = (t["name"] as string | undefined) ?? override.name ?? key;

    if (typeof t.execute !== "function") {
      out[key] = t;
      continue;
    }

    const extras: SynapseToolExtras = {
      name: explicitName,
    };
    if (override.scope !== undefined) extras.scope = override.scope;
    const resolvedAgent = override.agentId ?? opts.agentId;
    if (resolvedAgent !== undefined) extras.agentId = resolvedAgent;
    if (override.skip !== undefined) extras.skip = override.skip;

    if (extras.skip) {
      out[key] = t;
      continue;
    }

    out[key] = {
      ...t,
      execute: _instrumentExecute(
        explicitName,
        extras,
        t.execute as VercelToolExecute<unknown, unknown>,
      ),
    };
  }
  return out as T;
}

// ---------------------------------------------------------------------------
// getCallback — returns a pre-bound `synapseTool` factory using the
// install()-time agent id default.
// ---------------------------------------------------------------------------

/**
 * Returns a pre-configured `synapseTool` factory that uses the agent id
 * provided to `install({ framework: "vercel-ai", agentId: "..." })`.
 */
export function getCallback(): typeof synapseTool {
  return synapseTool;
}

// ---------------------------------------------------------------------------
// Framework registration — self-registers under "vercel-ai" and "vercel".
// ---------------------------------------------------------------------------

export interface VercelAIInstallOptions {
  agentId?: string;
  /** Inject a custom `tool()` factory (e.g. for tests). */
  toolFactory?: ToolFactoryFn;
  [key: string]: unknown;
}

function _installVercelAI(opts: Record<string, unknown>): void {
  const o = opts as VercelAIInstallOptions;
  if (typeof o.agentId === "string" && o.agentId) {
    _defaults.agentId = o.agentId;
  } else {
    const env = process.env["SYNAPSE_DEFAULT_AGENT_ID"];
    if (env) _defaults.agentId = env;
  }
  if (typeof o.toolFactory === "function") {
    _setToolFactory(o.toolFactory);
  }
  // eslint-disable-next-line no-console
  console.info(
    "synapse.install(framework='vercel-ai'): use `synapseTool` from " +
      "synapse-protocol/frameworks/vercel-ai in place of `tool` from " +
      "`ai`, or call `wrapVercelTools(myTools)` to bulk-instrument an " +
      "existing tool map.",
  );
}

registerFramework("vercel-ai", _installVercelAI);
registerFramework("vercel", _installVercelAI);
registerFramework("ai", _installVercelAI);
