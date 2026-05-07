/**
 * `synapse.install()` — TypeScript port of sdk-python/synapse/install.py.
 *
 * One-line bootstrap: configures the Synapse runtime + (optionally) hooks
 * a known framework so its tool dispatches get wrapped with `intend()`.
 *
 * ```ts
 * // Lazy: auto-detect everything
 * synapse.install();
 *
 * // Self-hosted with custom backends
 * synapse.install({
 *   busUrl: "redis://localhost:6379/0",
 *   sessionId: "my_session",
 * });
 * ```
 */
import {
  _getOrInitRuntime,
  shutdown as intendShutdown,
} from "./intend.js";
import { normalizeCriticalScopes } from "./policies/critical.js";
import { resolvePolicy } from "./policies/registry.js";
import type { MergePolicy } from "./policies/base.js";

// ---------------------------------------------------------------------------
// Framework registry
// ---------------------------------------------------------------------------
export type FrameworkInstallFn = (
  opts: Record<string, unknown>,
) => void | Promise<void>;

export const _FRAMEWORK_REGISTRY: Map<string, FrameworkInstallFn> = new Map();

/**
 * Plug-in entry point: register a framework adapter. `installFn` runs when
 * `install({ framework: name })` is called.
 */
export function registerFramework(
  name: string,
  installFn: FrameworkInstallFn,
): void {
  _FRAMEWORK_REGISTRY.set(name, installFn);
}

// ---------------------------------------------------------------------------
// Auto-detect — best-effort sniff of which agent framework is in use.
// ---------------------------------------------------------------------------
function _normalize(mod: string): string {
  if (mod.startsWith("autogen")) return "autogen";
  if (mod === "openai_swarm" || mod === "agents") return "openai_agents";
  return mod;
}

function _autodetectFramework(): string | null {
  const candidates = [
    "langgraph",
    "crewai",
    "autogen",
    "autogen_agentchat",
    "autogen_core",
    "agents",
    "openai_agents",
    "openai_swarm",
    "smolagents",
    "pydantic_ai",
    "@langchain/langgraph",
    "@openai/agents",
  ];

  // 1) If any candidate is already in require.cache (CJS), return it.
  // ESM has no cache we can sniff cheaply, so we fall through to a
  // resolve-based check.
  try {
    const req = (globalThis as { require?: NodeJS.Require }).require;
    if (req && (req as NodeJS.Require & { cache?: NodeJS.Dict<unknown> }).cache) {
      const cache = (req as NodeJS.Require & { cache: NodeJS.Dict<unknown> })
        .cache;
      for (const key of Object.keys(cache)) {
        for (const c of candidates) {
          if (key.includes(`/node_modules/${c}/`)) return _normalize(c);
        }
      }
    }
  } catch {
    /* swallow */
  }

  // 2) Try to resolve each candidate. Cheap and works for ESM too.
  try {
    const req =
      typeof require !== "undefined"
        ? require
        : ((globalThis as { require?: NodeJS.Require }).require as
            | NodeJS.Require
            | undefined);
    if (req && req.resolve) {
      for (const c of candidates) {
        try {
          req.resolve(c);
          return _normalize(c);
        } catch {
          /* not installed */
        }
      }
    }
  } catch {
    /* swallow */
  }

  return null;
}

// ---------------------------------------------------------------------------
// install()
// ---------------------------------------------------------------------------
export interface InstallOptions {
  framework?: string;
  busUrl?: string;
  stateDsn?: string;
  sessionId?: string;
  agentId?: string;
  /** Auto-detect framework if not explicit. Default true. */
  auto?: boolean;
  mergePolicy?: MergePolicy | string | null;
  criticalScopes?: string[];
  emitBeliefsFromToolResults?: boolean;
  /** Forwarded to the framework adapter's installFn. */
  frameworkOpts?: Record<string, unknown>;
}

export interface InstallResult {
  framework: string | null;
  mode: "offline" | "live" | undefined;
  busUrl: string | undefined;
  stateDsn: string | undefined;
  hooksInstalled: string[];
  mergePolicy: string | null;
  criticalScopes: string[];
  emitBeliefsFromToolResults: boolean;
}

export function install(opts: InstallOptions = {}): InstallResult {
  if (opts.sessionId && !process.env["SYNAPSE_SESSION_ID"]) {
    process.env["SYNAPSE_SESSION_ID"] = opts.sessionId;
  }
  if (opts.agentId && !process.env["SYNAPSE_DEFAULT_AGENT_ID"]) {
    process.env["SYNAPSE_DEFAULT_AGENT_ID"] = opts.agentId;
  }

  const initOpts: { busUrl?: string; stateDsn?: string } = {};
  if (opts.busUrl !== undefined) initOpts.busUrl = opts.busUrl;
  if (opts.stateDsn !== undefined) initOpts.stateDsn = opts.stateDsn;
  const rt = _getOrInitRuntime(initOpts);

  // Stash policy defaults so intend() picks them up.
  if (!rt.policy_defaults) rt.policy_defaults = {};
  const defaults = rt.policy_defaults;

  if (opts.mergePolicy !== undefined && opts.mergePolicy !== null) {
    defaults.merge_policy = resolvePolicy(opts.mergePolicy);
  }
  if (opts.criticalScopes !== undefined) {
    defaults.critical_scopes = normalizeCriticalScopes(opts.criticalScopes);
  }
  if (opts.emitBeliefsFromToolResults) {
    defaults.emit_beliefs_from_tool_results = true;
  }

  let framework = opts.framework ?? null;
  if (framework === null && opts.auto !== false) {
    framework = _autodetectFramework();
  }

  const hooks: string[] = [];
  if (framework) {
    const installFn = _FRAMEWORK_REGISTRY.get(framework);
    if (installFn === undefined) {
      console.warn(
        `synapse.install: no adapter registered for framework=${JSON.stringify(framework)}. ` +
          `Available: ${JSON.stringify([..._FRAMEWORK_REGISTRY.keys()])}. ` +
          `Falling back to manual synapse.intend().`,
      );
    } else {
      try {
        const result = installFn(opts.frameworkOpts ?? {});
        if (result && typeof (result as Promise<unknown>).then === "function") {
          // fire-and-forget; install() stays sync to mirror Python
          void (result as Promise<unknown>).catch((e) =>
            console.warn(
              `synapse.install: ${framework} install fn rejected`,
              e,
            ),
          );
        }
        hooks.push(framework);
      } catch (e) {
        console.warn(
          `synapse.install: ${framework} install fn threw`,
          e,
        );
      }
    }
  }

  return {
    framework,
    mode: rt.mode,
    busUrl: rt.busUrl,
    stateDsn: rt.stateDsn,
    hooksInstalled: hooks,
    mergePolicy: defaults.merge_policy
      ? defaults.merge_policy.name
      : null,
    criticalScopes: defaults.critical_scopes ?? [],
    emitBeliefsFromToolResults: !!defaults.emit_beliefs_from_tool_results,
  };
}

// ---------------------------------------------------------------------------
// shutdown — re-exported so callers don't have to know about intend.ts.
// ---------------------------------------------------------------------------
export async function shutdown(): Promise<void> {
  await intendShutdown();
}
