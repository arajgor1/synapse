/**
 * Base types for merge policies.
 *
 * Ported from `sdk-python/synapse/policies/base.py`.
 */
import type { Conflict } from "../types.js";

/** What the policy decided when it saw a CONFLICT. */
export enum MergeDecision {
  /** Caller's original action stands; just log. */
  PROCEED = "proceed",
  /** Fail the intention with SynapseConflict. */
  ABORT = "abort",
  /** Block then retry (handled by intend). */
  WAIT = "wait",
  /** auto_merge produced .merged_action */
  MERGED = "merged",
}

/** The policy's decision, returned to `synapse.intend()`. */
export interface MergeAction {
  decision: MergeDecision;
  /**
   * Only set when decision === MERGED — the new tool args / content the
   * caller should use instead of their original `proposedAction`.
   */
  mergedAction?: Record<string, unknown> | null;
  /** Free-form rationale (logged + surfaced to the agent's LLM if redirect). */
  rationale: string;
  /** Used when decision === WAIT */
  waitTimeoutMs?: number;
}

/**
 * Raised by a policy that decides ABORT.
 *
 * Carries the conflicts for the caller's framework to inspect. Most
 * framework adapters surface this as the framework's native error type
 * (LangGraph node error, CrewAI task failure, etc.).
 */
export class SynapseConflict extends Error {
  public readonly conflicts: Conflict[];
  public readonly scopes: string[];
  public readonly rationale: string;

  constructor(conflicts: Conflict[], scopes: string[], rationale = "") {
    const msg =
      rationale ||
      `Synapse CONFLICT on scope(s) ${JSON.stringify(scopes)}: ${conflicts.length} other agent(s) hold overlapping intentions`;
    super(msg);
    this.name = "SynapseConflict";
    this.conflicts = conflicts;
    this.scopes = scopes;
    this.rationale = rationale;
    Object.setPrototypeOf(this, SynapseConflict.prototype);
  }
}

/**
 * Minimal shape of an `IntentionHandle` used by policies. The full type
 * lives in `../intend` (A4 agent owns it). We define the structural subset
 * we depend on so this module typechecks standalone.
 */
export interface IntentionHandleLike {
  scope: string[];
  agentId: string;
  sessionId: string;
  intentionId?: string;
}

/**
 * A pluggable strategy for handling CONFLICTs at intend() time.
 *
 * Subclass and implement `resolve()` to add custom behavior. The five
 * built-ins (RedirectPolicy / WaitPolicy / AbortPolicy / AutoMergePolicy /
 * NoOpPolicy) cover the common cases.
 */
export abstract class MergePolicy {
  public name: string = "base";

  /**
   * Decide what to do given a conflict + the caller's planned action.
   *
   * @param handle the IntentionHandle from `synapse.intend()`.
   * @param conflicts list of Conflict envelope payloads.
   * @param proposedAction what the agent is about to do (tool args /
   *   content). Required for `auto_merge`; optional for others.
   */
  abstract resolve(
    handle: IntentionHandleLike,
    conflicts: Conflict[],
    proposedAction?: Record<string, unknown>,
  ): Promise<MergeAction>;

  // Singleton accessors — wired by `registry.ts` once concrete subclasses
  // are imported. Declared here so `MergePolicy.redirect` etc. are typed.
  static redirect: MergePolicy;
  static wait: MergePolicy;
  static abort: MergePolicy;
  static autoMerge: MergePolicy;
  static noOp: MergePolicy;
}
