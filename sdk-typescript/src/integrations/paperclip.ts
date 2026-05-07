/**
 * Synapse adapter for Paperclip AI.
 *
 * Paperclip exposes a server-side adapter registry (`registerServerAdapter`)
 * and a UI-side adapter registry (`registerUIAdapter`) — see Paperclip's
 * `adapter-plugin.md`. This module ships a Synapse-coordinated wrapper that:
 *
 *   1. Wraps an underlying Paperclip adapter (Anthropic, OpenAI, etc.) so
 *      every tool/task dispatch gets an INTENTION emitted to Synapse first.
 *   2. Listens for CONFLICT signals routed by the Synapse router and
 *      surfaces them as a Paperclip-native AdapterError so the existing
 *      Paperclip retry/escalation flow handles the pivot.
 *   3. Reports COST (token spend) back through Synapse's COST_REPORT.
 *
 * Usage in a Paperclip server bootstrap:
 *
 *   import { registerServerAdapter } from "paperclip/server/adapters/registry";
 *   import { wrapAdapterWithSynapse } from "@synapse-protocol/sdk/integrations/paperclip";
 *   import { anthropicAdapter } from "paperclip/server/adapters/anthropic";
 *
 *   const synapseBus = await Bus.connect(process.env.SYNAPSE_REDIS_URL!);
 *   const wrapped = wrapAdapterWithSynapse(anthropicAdapter, {
 *     bus: synapseBus,
 *     sessionId: process.env.PAPERCLIP_COMPANY_ID,
 *     // optional: per-agent scope rules from your Paperclip "org chart"
 *     scopeFromTask: (task) => [`paperclip.task:${task.id}:w`],
 *   });
 *   registerServerAdapter(wrapped);
 *
 * The wrapped adapter has the same shape as a built-in Paperclip adapter
 * (the framework's adapter type is open-ended per their phase-1 plugin spec)
 * so it slots in without any changes to Paperclip core.
 */

import type { Bus } from "../bus.js";
import { Agent } from "../agent.js";
import type { InferenceAdapter } from "../adapters/base.js";
import { MockAdapter } from "../adapters/mock.js";

// ---------------------------------------------------------------------------
// Paperclip adapter contract (replicated structurally — Paperclip uses these
// shapes per its packages/shared/src/adapter-type.ts and server/src/adapters/*).
// We don't import from paperclip directly so this works without Paperclip
// installed, and so users with different Paperclip versions can adopt.
// ---------------------------------------------------------------------------
export interface PaperclipTask {
  id: string;
  agentId: string;
  description?: string;
  // Paperclip carries an open metadata bag — used for goal, budget, etc.
  metadata?: Record<string, unknown>;
}

export interface PaperclipAdapterRequest {
  task: PaperclipTask;
  prompt: string;
  // Whatever else Paperclip's runtime passes through (model, params, ...).
  [key: string]: unknown;
}

export interface PaperclipAdapterResponse {
  text: string;
  tokensIn?: number;
  tokensOut?: number;
  estimatedUsd?: number;
  error?: { kind: string; message: string };
}

/** The shape Paperclip expects from any adapter. */
export interface PaperclipAdapter {
  type: string;
  invoke(request: PaperclipAdapterRequest): Promise<PaperclipAdapterResponse>;
}

// ---------------------------------------------------------------------------
// Synapse wrapper
// ---------------------------------------------------------------------------
export interface WrapWithSynapseOptions {
  /** Synapse bus, already connected. Required. */
  bus: Bus;
  /** Synapse session id. For Paperclip multi-tenancy, use companyId or
   *  a per-organization id so all agents in the same company share a
   *  coordination session. */
  sessionId: string;
  /**
   * Build the scope claim for this task. Default: emit on
   * `paperclip.task:{task.id}:w`. Customize to model your org-chart
   * boundaries (e.g. one scope per agent role + resource pair).
   */
  scopeFromTask?: (task: PaperclipTask) => string[];
  /**
   * If true, surface CONFLICT signals as an AdapterError on the response
   * so Paperclip's existing error path triggers escalation. Default: true.
   */
  failOnConflict?: boolean;
  /** Pre-execution gate window in ms before proceeding (Synapse default 50ms). */
  gateMs?: number;
  /**
   * Synapse-side inference backend used by the Agent (mock by default —
   * the real LLM call is still done by the wrapped Paperclip adapter).
   * The Synapse Agent's backend is only used for things like coordinator
   * communication, not the user-facing generation.
   */
  synapseBackend?: InferenceAdapter;
}

/**
 * Wrap a Paperclip adapter so every task dispatch participates in Synapse
 * coordination.
 */
export function wrapAdapterWithSynapse(
  inner: PaperclipAdapter,
  opts: WrapWithSynapseOptions,
): PaperclipAdapter {
  const scopeFromTask =
    opts.scopeFromTask ?? ((t) => [`paperclip.task:${t.id}:w`]);
  const failOnConflict = opts.failOnConflict ?? true;
  const gateMs = opts.gateMs ?? 50;
  const synapseBackend = opts.synapseBackend ?? new MockAdapter();

  // Per-Paperclip-task agent cache — one Synapse Agent per Paperclip agentId
  // in the session, so multiple tasks for the same agent share an inbox cursor.
  const agentCache = new Map<string, Agent>();

  async function ensureAgent(agentId: string): Promise<Agent> {
    let a = agentCache.get(agentId);
    if (a) return a;
    a = new Agent({
      id: agentId,
      session: opts.sessionId,
      backend: synapseBackend,
      bus: opts.bus,
      subscribes: [`paperclip.*`],
    });
    agentCache.set(agentId, a);
    return a;
  }

  return {
    type: `synapse:${inner.type}`,
    async invoke(request) {
      const t0 = Date.now();
      const agent = await ensureAgent(request.task.agentId);

      // Emit INTENTION before the adapter actually fires
      const [intentionId, conflicts] = await agent.emitIntention({
        action: { description: `paperclip:${inner.type}:${request.task.id}` },
        scope: scopeFromTask(request.task),
        expected_outcome: request.task.description ?? `paperclip task ${request.task.id}`,
        blocking: true,
        gateMs,
      });

      if (conflicts.length > 0) {
        if (failOnConflict) {
          // Surface as an AdapterError for Paperclip's error pipeline
          return {
            text: "",
            error: {
              kind: "synapse_conflict",
              message: `Scope conflict: ${conflicts[0]?.overlapping_scopes?.join(", ")}. Suggested: ${conflicts[0]?.suggested_resolution ?? "pivot"}.`,
            },
          };
        }
        // Otherwise just continue — caller's choice
      }

      // Execute the wrapped adapter
      let response: PaperclipAdapterResponse;
      try {
        response = await inner.invoke(request);
        // Mark intention resolved on success
        await agent.emitResolution({
          intentionId,
          outcome: response.error ? "failure" : "success",
          ...(response.error
            ? { state_diff: { error: response.error.message.slice(0, 200) } }
            : {}),
        });
      } catch (err) {
        await agent.emitResolution({
          intentionId,
          outcome: "failure",
          state_diff: { error: (err as Error).message.slice(0, 200) },
        });
        throw err;
      }

      // Optionally publish a COST_REPORT envelope back to the bus
      if (response.tokensIn !== undefined || response.tokensOut !== undefined) {
        const wallMs = Date.now() - t0;
        const env = {
          msg_id: intentionId, // shares parent for traceability
          type: "COST_REPORT" as const,
          version: "1.0",
          agent_id: request.task.agentId,
          session_id: opts.sessionId,
          parent_msg_id: intentionId,
          timestamp_ms: Date.now(),
          payload: {
            signal_id: intentionId,
            mechanism: "inbox_at_decision_point" as const,
            tokens_billed: (response.tokensIn ?? 0) + (response.tokensOut ?? 0),
            wall_clock_ms: wallMs,
            ...(response.estimatedUsd !== undefined && {
              estimated_usd: response.estimatedUsd,
            }),
          },
        };
        await opts.bus.publishSession(env);
      }

      return response;
    },
  };
}

// ---------------------------------------------------------------------------
// Convenience: build a fresh Synapse-only adapter (no inner) for testing
// the integration shape without a real Paperclip stack.
// ---------------------------------------------------------------------------
export function makeMockSynapsePaperclipAdapter(
  opts: WrapWithSynapseOptions,
): PaperclipAdapter {
  const dummyInner: PaperclipAdapter = {
    type: "mock",
    async invoke(req) {
      return {
        text: `mock paperclip response for task ${req.task.id}`,
        tokensIn: 50,
        tokensOut: 25,
        estimatedUsd: 0.0001,
      };
    },
  };
  return wrapAdapterWithSynapse(dummyInner, opts);
}
