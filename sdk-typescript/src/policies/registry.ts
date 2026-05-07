/**
 * Policy registry + the user-facing `MergePolicy.*` namespace.
 *
 * The `MergePolicy` class itself is the abstract base. The user-facing
 * constants live as class-level static attributes so
 * `MergePolicy.redirect` works ergonomically without users instantiating
 * policies themselves.
 *
 *     synapse.install({ mergePolicy: MergePolicy.redirect })
 *     synapse.install({ mergePolicy: MergePolicy.autoMerge })
 *
 * For custom policies, subclass `MergePolicy` and pass an instance.
 *
 * Ported from `sdk-python/synapse/policies/registry.py`.
 */
import { MergePolicy } from "./base.js";
import {
  AbortPolicy,
  AutoMergePolicy,
  NoOpPolicy,
  RedirectPolicy,
  WaitPolicy,
} from "./builtin.js";

// Singleton instances — the canonical values for `MergePolicy.*`
const REDIRECT = new RedirectPolicy();
const WAIT = new WaitPolicy();
const ABORT = new AbortPolicy();
const AUTO_MERGE = new AutoMergePolicy();
const NO_OP = new NoOpPolicy();

// Attach singletons as class-level attributes on the abstract base.
MergePolicy.redirect = REDIRECT;
MergePolicy.wait = WAIT;
MergePolicy.abort = ABORT;
MergePolicy.autoMerge = AUTO_MERGE;
MergePolicy.noOp = NO_OP;

export type PolicyLike = MergePolicy | string | null | undefined;

/**
 * Coerce `spec` into a MergePolicy instance.
 *
 * Accepts:
 *   - null / undefined -> null (means "no policy configured")
 *   - MergePolicy instance -> returned as-is
 *   - string ("redirect" / "wait" / "abort" / "auto_merge" / "no_op")
 *     -> the matching singleton
 */
export function resolvePolicy(spec: PolicyLike): MergePolicy | null {
  if (spec === null || spec === undefined) return null;
  if (spec instanceof MergePolicy) return spec;
  if (typeof spec === "string") {
    const s = spec.replace(/-/g, "_").trim().toLowerCase();
    const map: Record<string, MergePolicy> = {
      redirect: REDIRECT,
      wait: WAIT,
      abort: ABORT,
      auto_merge: AUTO_MERGE,
      automerge: AUTO_MERGE,
      merge: AUTO_MERGE,
      no_op: NO_OP,
      noop: NO_OP,
    };
    return map[s] ?? null;
  }
  throw new TypeError(
    `mergePolicy must be null | string | MergePolicy, got ${typeof spec}`,
  );
}

// Re-export singletons by name for convenience
export {
  REDIRECT as redirectPolicy,
  WAIT as waitPolicy,
  ABORT as abortPolicy,
  AUTO_MERGE as autoMergePolicy,
  NO_OP as noOpPolicy,
};
