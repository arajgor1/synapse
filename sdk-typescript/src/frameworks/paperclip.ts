/**
 * Paperclip framework adapter for `synapse.install({ framework: "paperclip" })`.
 *
 * This is a thin compatibility layer that registers Paperclip with the v0.2
 * universal install path. The actual wrapping happens at call time via
 * `wrapAdapterWithSynapse()` from `../integrations/paperclip.js`; this module
 * only stashes the install-time defaults so the wrapper picks them up.
 *
 * Usage:
 *
 *   import synapse from "@synapse-protocol/sdk";
 *   import "@synapse-protocol/sdk/frameworks/paperclip"; // self-registers
 *   synapse.install({
 *     framework: "paperclip",
 *     bus: myBus,                // optional default bus
 *     sessionId: "company_123",
 *     mergePolicy: synapse.MergePolicy.autoMerge,
 *     frameworkOpts: {
 *       gateMs: 100,
 *       scopeFromTask: (t) => [`paperclip.task:${t.id}:w`],
 *     },
 *   });
 *
 *   // Then call the v0.1 wrapper as usual — defaults are picked up:
 *   const wrapped = wrapAdapterWithSynapse(anthropicAdapter, {
 *     bus: myBus,
 *     sessionId: "company_123",
 *   });
 */
import type { Bus } from "../bus.js";
import type { InferenceAdapter } from "../adapters/base.js";
import type { MergePolicy } from "../policies/base.js";
import { registerFramework } from "../install.js";

// ---------------------------------------------------------------------------
// Defaults stash — read by wrapAdapterWithSynapse() to pick up install-time
// options without changing its public signature.
// ---------------------------------------------------------------------------
export interface PaperclipFrameworkDefaults {
  bus?: Bus;
  sessionId?: string;
  scopeFromTask?: (t: { id: string; agentId: string }) => string[];
  failOnConflict?: boolean;
  gateMs?: number;
  synapseBackend?: InferenceAdapter;
  mergePolicy?: MergePolicy | string | null;
  criticalScopes?: string[];
}

/**
 * Module-level defaults — populated by `install({ framework: "paperclip", ... })`.
 * Exported with an underscore prefix to signal "internal but observable for tests".
 */
export const _paperclipDefaults: PaperclipFrameworkDefaults = {};

/** Reset all stashed defaults — used by tests. */
export function _resetPaperclipDefaults(): void {
  for (const k of Object.keys(_paperclipDefaults) as Array<
    keyof PaperclipFrameworkDefaults
  >) {
    delete _paperclipDefaults[k];
  }
}

// ---------------------------------------------------------------------------
// install_fn — registered under "paperclip"
// ---------------------------------------------------------------------------
function _installPaperclip(opts: Record<string, unknown>): void {
  // Keys we accept — anything else is ignored (forward-compatible).
  if (opts["bus"] !== undefined) {
    _paperclipDefaults.bus = opts["bus"] as Bus;
  }
  if (typeof opts["sessionId"] === "string") {
    _paperclipDefaults.sessionId = opts["sessionId"] as string;
  }
  if (typeof opts["scopeFromTask"] === "function") {
    _paperclipDefaults.scopeFromTask = opts["scopeFromTask"] as (t: {
      id: string;
      agentId: string;
    }) => string[];
  }
  if (typeof opts["failOnConflict"] === "boolean") {
    _paperclipDefaults.failOnConflict = opts["failOnConflict"] as boolean;
  }
  if (typeof opts["gateMs"] === "number") {
    _paperclipDefaults.gateMs = opts["gateMs"] as number;
  }
  if (opts["synapseBackend"] !== undefined) {
    _paperclipDefaults.synapseBackend = opts["synapseBackend"] as InferenceAdapter;
  }
  if (opts["mergePolicy"] !== undefined) {
    _paperclipDefaults.mergePolicy = opts["mergePolicy"] as
      | MergePolicy
      | string
      | null;
  }
  if (Array.isArray(opts["criticalScopes"])) {
    _paperclipDefaults.criticalScopes = opts["criticalScopes"] as string[];
  }
}

// Self-register on import — same pattern as Python frameworks/*.
registerFramework("paperclip", _installPaperclip);
