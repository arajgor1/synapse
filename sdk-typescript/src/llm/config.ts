/** BYO-LLM configuration — module-level singleton mirroring synapse.llm.config (Python).
 *
 * Synapse never makes a paid LLM call without explicit caller config.
 * If `setLlm()` is never called, Synapse runs in **rules-only mode**:
 * `getLlm()` / `getInternalLlm()` return `null` and LLM-mediated paths
 * are expected to gracefully no-op.
 */
import type { InferenceAdapter } from "../adapters/base.js";

export interface LLMConfig {
  primary: InferenceAdapter | null;
  internal: InferenceAdapter | null;
}

const _config: LLMConfig = { primary: null, internal: null };
let _loggedUnsetWarning = false;

/** Heuristic: an InferenceAdapter must expose `capabilities` (with backend_id)
 *  and the four streaming methods. We don't require `instanceof` so that bridge
 *  adapters (plain classes) and user-defined adapters both pass.
 */
function isInferenceAdapter(value: unknown): value is InferenceAdapter {
  if (value === null || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  const caps = v["capabilities"];
  if (caps === null || typeof caps !== "object") return false;
  if (typeof (caps as Record<string, unknown>)["backend_id"] !== "string") return false;
  return (
    typeof v["startStream"] === "function" &&
    typeof v["readTokens"] === "function" &&
    typeof v["injectAndContinue"] === "function" &&
    typeof v["cancel"] === "function"
  );
}

/** Configure the LLM(s) Synapse will use for internal reasoning.
 *
 * @param primary - Adapter used for user-facing decisions (auto-merge, etc.). Required.
 * @param internal - Cheaper adapter for high-frequency calls. Optional — defaults to `primary`.
 */
export function setLlm(
  primary: InferenceAdapter,
  internal?: InferenceAdapter | null,
): void {
  if (!isInferenceAdapter(primary)) {
    throw new TypeError(
      "synapse.setLlm() expects an InferenceAdapter, got " +
        `${primary === null ? "null" : typeof primary}. Use synapse.fromAnthropic() / ` +
        "synapse.fromOpenAI() / synapse.fromVercelAI() / synapse.fromLangChainJS() " +
        "to wrap a vendor client.",
    );
  }
  if (internal !== undefined && internal !== null && !isInferenceAdapter(internal)) {
    throw new TypeError(
      `synapse.setLlm() internal expects an InferenceAdapter, got ${typeof internal}.`,
    );
  }
  _config.primary = primary;
  _config.internal = internal ?? null;
}

/** Return the primary adapter, or null if unconfigured. */
export function getLlm(): InferenceAdapter | null {
  if (_config.primary === null && !_loggedUnsetWarning) {
    _loggedUnsetWarning = true;
    // Mirror Python's one-shot info log; use console.info so tests can silence it.
    // eslint-disable-next-line no-console
    console.info(
      "synapse: no LLM configured (synapse.setLlm() was not called). " +
        "L1 + L2 routing still work; LLM-mediated features are no-ops in this run.",
    );
  }
  return _config.primary;
}

/** Return the internal (cheap) adapter, or fall back to primary. */
export function getInternalLlm(): InferenceAdapter | null {
  return _config.internal ?? getLlm();
}

export function isConfigured(): boolean {
  return _config.primary !== null;
}

/** Reset the LLM config (mostly for tests). */
export function clear(): void {
  _config.primary = null;
  _config.internal = null;
  _loggedUnsetWarning = false;
}
