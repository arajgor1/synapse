/**
 * v0.2 framework adapter for OpenClaw.
 *
 * Registers itself with the install() framework registry under the name
 * `"openclaw"`. After `synapse.install({ framework: "openclaw", ... })`,
 * the user's existing `wrapExtensionWithSynapse(extension, opts)` call
 * automatically benefits from the install()-time MergePolicy,
 * critical_scopes, and BELIEF auto-extraction — without any additional
 * code changes.
 *
 * Unlike LangGraph or CrewAI, OpenClaw does not have a single global
 * dispatcher we can monkey-patch. Each extension's `tools` array is
 * registered independently. So the install fn is essentially a
 * registration breadcrumb — the actual instrumentation happens when the
 * user calls `wrapExtensionWithSynapse()`. We export a thin
 * `installOpenClaw()` that callers can also invoke directly if they
 * want the registry side-effect without going through `install()`.
 *
 * Example:
 *
 * ```ts
 * synapse.install({
 *   framework: "openclaw",
 *   bus: myBus,
 *   sessionId: process.env.OPENCLAW_USER_ID,
 *   mergePolicy: synapse.MergePolicy.autoMerge,
 * });
 * const wrapped = wrapExtensionWithSynapse(myExtension, { ... });
 * ```
 */
import { registerFramework } from "../install.js";
import {
  wrapExtensionWithSynapse,
  makeSynapseExtension,
  type OpenClawExtension,
  type OpenClawSynapseOptions,
} from "../integrations/openclaw.js";

// ---------------------------------------------------------------------------
// Bookkeeping — track installs so tests + diagnostics can see what fired.
// ---------------------------------------------------------------------------
interface OpenClawInstallState {
  installed: boolean;
  options?: Record<string, unknown>;
}

const _state: OpenClawInstallState = { installed: false };

/** Test/diagnostic accessor — returns the most recent install state. */
export function _getOpenClawState(): OpenClawInstallState {
  return _state;
}

/** Test helper — reset framework install state. */
export function _resetOpenClawState(): void {
  _state.installed = false;
  delete _state.options;
}

// ---------------------------------------------------------------------------
// install fn — runs when synapse.install({ framework: "openclaw" }) fires.
// ---------------------------------------------------------------------------
function openclawInstallFn(opts: Record<string, unknown>): void {
  // OpenClaw exposes no global dispatcher — there's nothing to monkey-patch
  // at the framework level. The install fn just records that the framework
  // hook ran, so subsequent wrapExtensionWithSynapse() calls are documented
  // as "installed", and so install() can return hooksInstalled=["openclaw"].
  _state.installed = true;
  _state.options = { ...opts };
}

// ---------------------------------------------------------------------------
// Wrapper helpers — re-exported through the framework module so users have
// a single import path: `from "@synapse-protocol/sdk/frameworks/openclaw"`.
// ---------------------------------------------------------------------------
export {
  wrapExtensionWithSynapse,
  makeSynapseExtension,
  type OpenClawExtension,
  type OpenClawSynapseOptions,
};

// ---------------------------------------------------------------------------
// Self-registration — runs at import time so consumers don't need a
// separate "register" step. Idempotent: calling registerFramework with the
// same name overrides the prior fn.
// ---------------------------------------------------------------------------
registerFramework("openclaw", openclawInstallFn);

/**
 * Convenience: explicitly register the OpenClaw framework adapter.
 * Calling this is normally not needed (importing the module already
 * registers), but useful in tests that have cleared the registry.
 */
export function installOpenClaw(): void {
  registerFramework("openclaw", openclawInstallFn);
}
