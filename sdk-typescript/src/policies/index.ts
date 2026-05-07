/**
 * Merge policies — what to do when `synapse.intend()` detects a CONFLICT.
 *
 * Public exports for the policies module. See SKILL.md / Python docstring
 * in `sdk-python/synapse/policies/__init__.py` for the conceptual overview.
 */
export {
  MergePolicy,
  MergeDecision,
  SynapseConflict,
  type MergeAction,
  type IntentionHandleLike,
} from "./base.js";

export {
  RedirectPolicy,
  WaitPolicy,
  AbortPolicy,
  AutoMergePolicy,
  NoOpPolicy,
} from "./builtin.js";

export {
  resolvePolicy,
  type PolicyLike,
  redirectPolicy,
  waitPolicy,
  abortPolicy,
  autoMergePolicy,
  noOpPolicy,
} from "./registry.js";

export { criticalScopeMatch, normalizeCriticalScopes } from "./critical.js";
