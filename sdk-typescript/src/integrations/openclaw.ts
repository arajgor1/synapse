/**
 * Synapse adapter for OpenClaw.
 *
 * OpenClaw is a personal AI assistant with an extension/plugin architecture
 * (`extensions/<name>/plugin-registration.ts` is the canonical pattern). Each
 * extension can register tools that the agent can invoke. Synapse fits at
 * exactly the same layer: register a Synapse "extension" whose tools wrap
 * other tools' dispatch with INTENTION / CONFLICT / RESOLUTION emissions.
 *
 * Two integration modes:
 *
 *   1. As a wrapper around an existing extension's tool registry. The user's
 *      OpenClaw bootstrap calls `wrapExtensionWithSynapse(extension, opts)`
 *      and registers the wrapped extension instead. All tools provided by
 *      that extension now coordinate via Synapse.
 *
 *   2. As a standalone "synapse" extension that exposes a small toolset
 *      (`synapse_intention`, `synapse_resolution`, `synapse_conflicts`)
 *      so OpenClaw skill authors can manually opt their custom tools into
 *      coordination without wrapping.
 *
 * Note: OpenClaw's exact plugin-registration API has shifted across
 * versions. We model the adapter against a minimal duck-typed interface so
 * the integration works across plugin API revisions.
 */

import type { Bus } from "../bus.js";
import { Agent } from "../agent.js";
import type { InferenceAdapter } from "../adapters/base.js";
import { MockAdapter } from "../adapters/mock.js";

// ---------------------------------------------------------------------------
// Minimal OpenClaw plugin shape (duck-typed; matches what
// extensions/browser/plugin-registration.ts and similar export)
// ---------------------------------------------------------------------------
export interface OpenClawTool {
  name: string;
  description?: string;
  /** Free-form schema (zod / json-schema / handler — varies by extension) */
  inputSchema?: unknown;
  /**
   * Tool execution. OpenClaw extensions invoke this with the agent's args.
   * The integration wraps THIS function.
   */
  handler: (args: Record<string, unknown>, ctx?: any) => Promise<unknown>;
  /** Heuristic — if false, skip Synapse INTENTION (read-only tool). */
  isWrite?: boolean;
}

export interface OpenClawExtension {
  name: string;
  tools: OpenClawTool[];
  // Other registration metadata varies by version; we only touch tools[].
  [key: string]: unknown;
}

export interface OpenClawSynapseOptions {
  bus: Bus;
  /** Synapse session id. Use the OpenClaw user/workspace id. */
  sessionId: string;
  /** Synapse agent id. Defaults to "openclaw". */
  agentId?: string;
  /**
   * Map a tool call to a Synapse scope claim. Default: convention-based
   * (file ops -> repo.fs.<path>:w, others -> openclaw.tool.<name>:w).
   */
  scopeFromCall?: (tool: OpenClawTool, args: Record<string, unknown>) => string[];
  /** Pre-execution gate window. */
  gateMs?: number;
  /** If true, throw on CONFLICT; otherwise log and continue. */
  failOnConflict?: boolean;
  /** Synapse-side backend used by the Agent (mock by default). */
  synapseBackend?: InferenceAdapter;
  /**
   * Predicate to decide whether a tool is a "write" (INTENTION required).
   * Defaults to checking tool.isWrite, then a name-based heuristic.
   */
  isWriteTool?: (tool: OpenClawTool) => boolean;
}

const DEFAULT_WRITE_TOOL_NAMES = [
  "write", "edit", "patch", "delete", "create", "update", "execute",
  "run", "send", "post", "publish", "deploy", "commit",
];

function defaultIsWrite(tool: OpenClawTool): boolean {
  if (tool.isWrite !== undefined) return tool.isWrite;
  const lower = tool.name.toLowerCase();
  return DEFAULT_WRITE_TOOL_NAMES.some((kw) => lower.includes(kw));
}

function defaultScope(tool: OpenClawTool, args: Record<string, unknown>): string[] {
  const path = args["path"] ?? args["file_path"];
  if (typeof path === "string" && path) {
    const safe = path.replace(/[^a-zA-Z0-9._/-]/g, "_").replace(/^\/+/, "");
    return [`repo.fs.${safe}:w`];
  }
  return [`openclaw.tool.${tool.name}:w`];
}

// ---------------------------------------------------------------------------
// Wrap an entire OpenClaw extension's tool list with Synapse coordination.
// ---------------------------------------------------------------------------
export function wrapExtensionWithSynapse(
  extension: OpenClawExtension,
  opts: OpenClawSynapseOptions,
): OpenClawExtension {
  const agentId = opts.agentId ?? "openclaw";
  const isWrite = opts.isWriteTool ?? defaultIsWrite;
  const scopeFromCall = opts.scopeFromCall ?? defaultScope;
  const gateMs = opts.gateMs ?? 50;
  const failOnConflict = opts.failOnConflict ?? false;
  const synapseBackend = opts.synapseBackend ?? new MockAdapter();

  // Single shared agent across all tools in this extension
  const agent = new Agent({
    id: agentId,
    session: opts.sessionId,
    backend: synapseBackend,
    subscribes: ["openclaw.*", "repo.*"],
    bus: opts.bus,
  });

  const wrappedTools: OpenClawTool[] = extension.tools.map((tool) => {
    if (!isWrite(tool)) {
      // Read-only tool — pass through, no overhead
      return tool;
    }
    return {
      ...tool,
      handler: async (args, ctx) => {
        const [intentId, conflicts] = await agent.emitIntention({
          action: { tool: tool.name, args },
          scope: scopeFromCall(tool, args),
          expected_outcome: tool.description ?? `openclaw:${tool.name}`,
          blocking: true,
          gateMs,
        });
        if (conflicts.length > 0) {
          if (failOnConflict) {
            throw new Error(
              `Synapse CONFLICT on ${tool.name}: ` +
                `${conflicts[0]?.suggested_resolution ?? "pivot"}`,
            );
          }
          // log and continue
          console.warn(
            `[synapse] CONFLICT on ${tool.name} but failOnConflict=false; proceeding`,
          );
        }
        let outcome: "success" | "failure" = "success";
        let errMsg: string | undefined;
        try {
          const result = await tool.handler(args, ctx);
          return result;
        } catch (e) {
          outcome = "failure";
          errMsg = (e as Error).message?.slice(0, 200);
          throw e;
        } finally {
          await agent.emitResolution({
            intentionId: intentId,
            outcome,
            ...(errMsg ? { state_diff: { error: errMsg } } : {}),
          });
        }
      },
    };
  });

  return { ...extension, name: `${extension.name}+synapse`, tools: wrappedTools };
}

// ---------------------------------------------------------------------------
// Standalone "synapse" extension — exports tools the agent itself can call.
// ---------------------------------------------------------------------------
export function makeSynapseExtension(
  opts: OpenClawSynapseOptions,
): OpenClawExtension {
  const agentId = opts.agentId ?? "openclaw";
  const synapseBackend = opts.synapseBackend ?? new MockAdapter();

  const agent = new Agent({
    id: agentId,
    session: opts.sessionId,
    backend: synapseBackend,
    bus: opts.bus,
  });

  const tools: OpenClawTool[] = [
    {
      name: "synapse_intention",
      description:
        "Emit a Synapse INTENTION. Returns the intention id and any conflicts received during the pre-execution gate.",
      isWrite: false,
      handler: async (args) => {
        const [id, conflicts] = await agent.emitIntention({
          action: { description: String(args["description"] ?? "manual intention") },
          scope: (args["scope"] as string[]) ?? ["openclaw.manual:w"],
          expected_outcome: String(args["expected_outcome"] ?? "?"),
          blocking: Boolean(args["blocking"] ?? true),
          gateMs: Number(args["gate_ms"] ?? 50),
        });
        return { intention_id: id, conflicts };
      },
    },
    {
      name: "synapse_resolution",
      description:
        "Emit a RESOLUTION for a previously-emitted intention. outcome ∈ {success,failure,partial}.",
      isWrite: false,
      handler: async (args) => {
        const id = await agent.emitResolution({
          intentionId: String(args["intention_id"]),
          outcome: (args["outcome"] as "success" | "failure" | "partial") ?? "success",
        });
        return { resolution_id: id };
      },
    },
    {
      name: "synapse_drain_signals",
      description: "Drain pending CONFLICT/BLOCK signals from the agent's inbox.",
      isWrite: false,
      handler: async () => {
        const sigs = await agent.drainSignals();
        return { signals: sigs.map((e) => ({ type: e.type, payload: e.payload })) };
      },
    },
  ];

  return { name: "synapse", tools };
}
