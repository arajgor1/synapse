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
 * v0.2 internals: this module now delegates to `synapse.intendWith()` so
 *   callers automatically pick up the universal merge-policy machinery
 *   (auto_merge, redirect, abort, critical_scopes) and belief auto-extraction
 *   without changing their code. The `wrapAdapterWithSynapse` /
 *   `makeMockSynapsePaperclipAdapter` public API is unchanged from v0.1.
 *
 * Usage in a Paperclip server bootstrap:
 *
 *   import { registerServerAdapter } from "paperclip/server/adapters/registry";
 *   import { wrapAdapterWithSynapse } from "synapse-protocol/integrations/paperclip";
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
 * For the v0.2 install() pattern, see `frameworks/paperclip.ts`:
 *
 *   import synapse from "synapse-protocol";
 *   import "synapse-protocol/frameworks/paperclip";
 *   synapse.install({
 *     framework: "paperclip",
 *     bus: myBus,
 *     sessionId: "company_123",
 *     mergePolicy: synapse.MergePolicy.autoMerge,
 *   });
 *   // Then call wrapAdapterWithSynapse normally — defaults are picked up.
 */

import type { Bus } from "../bus.js";
import { Agent } from "../agent.js";
import type { InferenceAdapter } from "../adapters/base.js";
import { MockAdapter } from "../adapters/mock.js";
import { intendWith, _runtime } from "../intend.js";
import { SynapseConflict, type MergePolicy } from "../policies/base.js";
import { _paperclipDefaults } from "../frameworks/paperclip.js";

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
  /**
   * Optional MergePolicy override — falls back to install-time default
   * configured via `synapse.install({ framework: "paperclip", mergePolicy })`.
   */
  mergePolicy?: MergePolicy | string | null;
  /**
   * Optional critical-scopes override — falls back to install-time default.
   */
  criticalScopes?: string[];
}

/**
 * Wrap a Paperclip adapter so every task dispatch participates in Synapse
 * coordination via `synapse.intendWith()`.
 */
export function wrapAdapterWithSynapse(
  inner: PaperclipAdapter,
  opts: WrapWithSynapseOptions,
): PaperclipAdapter {
  const scopeFromTask =
    opts.scopeFromTask ??
    _paperclipDefaults.scopeFromTask ??
    ((t) => [`paperclip.task:${t.id}:w`]);
  const failOnConflict =
    opts.failOnConflict ?? _paperclipDefaults.failOnConflict ?? true;
  const gateMs = opts.gateMs ?? _paperclipDefaults.gateMs ?? 50;
  const synapseBackend =
    opts.synapseBackend ??
    _paperclipDefaults.synapseBackend ??
    new MockAdapter();
  const mergePolicy =
    opts.mergePolicy !== undefined
      ? opts.mergePolicy
      : _paperclipDefaults.mergePolicy ?? null;
  const criticalScopes =
    opts.criticalScopes !== undefined
      ? opts.criticalScopes
      : _paperclipDefaults.criticalScopes;

  // Per-Paperclip-task agent cache — one Synapse Agent per Paperclip agentId
  // in the session, so multiple tasks for the same agent share an inbox cursor.
  // We pre-seed `_runtime.agents` so `intend()`'s `_getAgent()` picks up our
  // bus-bound agent on first invoke (cache check happens before bus init).
  function ensureRuntimeAgent(agentId: string): Agent {
    const cacheKey = `${opts.sessionId}::${agentId}`;
    if (!_runtime.agents) _runtime.agents = new Map<string, Agent>();
    const cached = _runtime.agents.get(cacheKey);
    if (cached) return cached;
    const agent = new Agent({
      id: agentId,
      session: opts.sessionId,
      backend: synapseBackend,
      bus: opts.bus,
      subscribes: [`paperclip.*`],
    });
    _runtime.agents.set(cacheKey, agent);
    return agent;
  }

  return {
    type: `synapse:${inner.type}`,
    async invoke(request) {
      const t0 = Date.now();
      // Pre-seed the runtime cache before intendWith() looks the agent up.
      ensureRuntimeAgent(request.task.agentId);

      let response: PaperclipAdapterResponse | undefined;
      let conflictResponse: PaperclipAdapterResponse | undefined;
      let intentionId = "";

      try {
        await intendWith(
          {
            scope: scopeFromTask(request.task),
            agent: request.task.agentId,
            session: opts.sessionId,
            expectedOutcome:
              request.task.description ?? `paperclip task ${request.task.id}`,
            blocking: true,
            gateMs,
            mergePolicy,
            ...(criticalScopes !== undefined ? { criticalScopes } : {}),
            proposedAction: {
              tool: `paperclip:${inner.type}`,
              taskId: request.task.id,
              prompt: request.prompt,
            },
          },
          async (handle) => {
            intentionId = handle.intentionId;

            // Legacy v0.1 behavior: when failOnConflict=true and no policy
            // resolved the conflict, surface it as an AdapterError on the
            // response (Paperclip retry/escalation hook).
            if (
              handle.hasConflicts &&
              handle.mergedAction === undefined &&
              failOnConflict
            ) {
              const c = handle.conflicts[0];
              conflictResponse = {
                text: "",
                error: {
                  kind: "synapse_conflict",
                  message: `Scope conflict: ${(c?.overlapping_scopes ?? []).join(", ")}. Suggested: ${c?.suggested_resolution ?? "pivot"}.`,
                },
              };
              handle.setStateDiff({
                synapse_conflict: true,
                surfaced_as: "adapter_error",
              });
              return;
            }

            // If a policy produced a merged_action, route the merged content
            // into the request's prompt for downstream adapters that honor it.
            const effectiveRequest =
              handle.mergedAction && typeof handle.mergedAction === "object"
                ? {
                    ...request,
                    ...(typeof handle.mergedAction["prompt"] === "string"
                      ? { prompt: handle.mergedAction["prompt"] as string }
                      : {}),
                    synapseMergedAction: handle.mergedAction,
                  }
                : request;

            response = await inner.invoke(effectiveRequest);
            if (response.error) {
              handle.markFailed(response.error.message);
            }
          },
        );
      } catch (err) {
        // SynapseConflict from policy.ABORT: convert to AdapterError when
        // failOnConflict is true; otherwise let it propagate.
        if (err instanceof SynapseConflict && failOnConflict) {
          return {
            text: "",
            error: {
              kind: "synapse_conflict",
              message: err.message,
            },
          };
        }
        throw err;
      }

      if (conflictResponse) return conflictResponse;
      if (!response) {
        // Defensive — should not happen unless inner adapter returned undefined.
        return { text: "" };
      }

      // Optionally publish a COST_REPORT envelope back to the bus
      if (response.tokensIn !== undefined || response.tokensOut !== undefined) {
        const wallMs = Date.now() - t0;
        const costEnv = {
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
        await opts.bus.publishSession(costEnv);
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
