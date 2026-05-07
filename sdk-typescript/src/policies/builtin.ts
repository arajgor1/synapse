/**
 * Five built-in MergePolicies covering the common cases.
 *
 * Ported from `sdk-python/synapse/policies/builtin.py`.
 *
 * NOTE on cross-module imports: `AutoMergePolicy.resolve()` reaches into
 * `../llm/config` and `../intend` which are owned by A1/A4 agents and may
 * not exist when this module is first compiled in isolation. We use
 * dynamic `import()` calls inside `resolve()` so the static graph stays
 * lean and test code can `vi.mock()` those module specifiers.
 */
import {
  MergeAction,
  MergeDecision,
  MergePolicy,
  type IntentionHandleLike,
} from "./base.js";
import type { Conflict, ConflictingIntention } from "../types.js";

// ---------------------------------------------------------------------------
// NoOp — proceed with a warning. Equivalent to v0.1 behavior.
// ---------------------------------------------------------------------------
export class NoOpPolicy extends MergePolicy {
  public override name = "no_op";

  async resolve(
    _handle: IntentionHandleLike,
    conflicts: Conflict[],
    _proposedAction?: Record<string, unknown>,
  ): Promise<MergeAction> {
    return {
      decision: MergeDecision.PROCEED,
      rationale: `Proceeding through ${conflicts.length} conflict(s) (no_op policy).`,
    };
  }
}

// ---------------------------------------------------------------------------
// Abort — fail the intention with a SynapseConflict.
// ---------------------------------------------------------------------------
export class AbortPolicy extends MergePolicy {
  public override name = "abort";

  async resolve(
    handle: IntentionHandleLike,
    conflicts: Conflict[],
    _proposedAction?: Record<string, unknown>,
  ): Promise<MergeAction> {
    return {
      decision: MergeDecision.ABORT,
      rationale:
        `Aborted: ${conflicts.length} other agent(s) hold conflicting ` +
        `intentions on ${JSON.stringify(handle.scope)}. Caller should pivot.`,
    };
  }
}

// ---------------------------------------------------------------------------
// Wait — block until prior conflicts resolve, then proceed.
// ---------------------------------------------------------------------------
export class WaitPolicy extends MergePolicy {
  public override name = "wait";
  public timeoutMs: number;

  constructor(timeoutMs = 5000) {
    super();
    this.timeoutMs = timeoutMs;
  }

  async resolve(
    _handle: IntentionHandleLike,
    conflicts: Conflict[],
    _proposedAction?: Record<string, unknown>,
  ): Promise<MergeAction> {
    return {
      decision: MergeDecision.WAIT,
      waitTimeoutMs: this.timeoutMs,
      rationale: `Waiting up to ${this.timeoutMs}ms for ${conflicts.length} prior intention(s) to resolve.`,
    };
  }
}

// ---------------------------------------------------------------------------
// Redirect — re-emit with the other agent's recent work as context.
// ---------------------------------------------------------------------------
export class RedirectPolicy extends MergePolicy {
  public override name = "redirect";

  async resolve(
    handle: IntentionHandleLike,
    conflicts: Conflict[],
    _proposedAction?: Record<string, unknown>,
  ): Promise<MergeAction> {
    const otherIds = new Set<string>();
    for (const c of conflicts) {
      const cis: ConflictingIntention[] = c.conflicting_intentions ?? [];
      for (const ci of cis) {
        if (ci.agent_id) otherIds.add(ci.agent_id);
      }
    }
    const others = otherIds.size > 0 ? Array.from(otherIds).sort() : ["other agent(s)"];

    const suggested = conflicts
      .map((c) => c.suggested_resolution || "pivot")
      .join(", ");

    const rationale =
      `Other agent(s) (${others.join(", ")}) hold overlapping ` +
      `intention(s) on scope ${JSON.stringify(handle.scope)}. Suggested action: ` +
      `${suggested}. Caller should pivot — re-prompt the LLM with ` +
      `the other agent(s)' recent work in context, then re-invoke.`;

    return {
      decision: MergeDecision.PROCEED,
      rationale,
    };
  }
}

// ---------------------------------------------------------------------------
// Auto-merge — opt-in: ask the user's BYO-LLM to merge two writes.
// ---------------------------------------------------------------------------

interface PriorContent {
  agentId: string;
  intentionId: string;
  content: string;
}

export class AutoMergePolicy extends MergePolicy {
  public override name = "auto_merge";
  public contentKey: string;

  constructor(opts: { contentKey?: string } = {}) {
    super();
    this.contentKey = opts.contentKey ?? "content";
  }

  async resolve(
    handle: IntentionHandleLike,
    conflicts: Conflict[],
    proposedAction?: Record<string, unknown>,
  ): Promise<MergeAction> {
    // Dynamic import to keep static graph lean and to make test-time
    // mocking via `vi.mock("../llm/config", ...)` straightforward.
    const llmConfig = (await import("../llm/config.js").catch(() => null)) as
      | { getInternalLlm?: () => unknown }
      | null;
    const getInternalLlm = llmConfig?.getInternalLlm;
    const llm = (getInternalLlm ? getInternalLlm() : null) as LlmLike | null;

    if (!llm) {
      return {
        decision: MergeDecision.PROCEED,
        rationale:
          "auto_merge skipped (no LLM); use synapse.setLlm() to enable.",
      };
    }

    if (!proposedAction || !(this.contentKey in proposedAction)) {
      return {
        decision: MergeDecision.PROCEED,
        rationale:
          `auto_merge requires proposedAction[${JSON.stringify(this.contentKey)}] — ` +
          `caller didn't supply it. Falling back to redirect.`,
      };
    }

    const priors = await fetchAllPriorContent(handle, conflicts, this.contentKey);
    if (priors.length === 0) {
      return {
        decision: MergeDecision.PROCEED,
        rationale:
          "auto_merge: couldn't fetch prior agent's content " +
          "(state graph unavailable or no state_diff). Redirecting.",
      };
    }

    const myContent = String(proposedAction[this.contentKey] ?? "");
    const merged = await llmMergeMulti(llm, {
      priors,
      myAgent: handle.agentId,
      myContent,
      scope: handle.scope,
    });

    if (!merged) {
      return {
        decision: MergeDecision.PROCEED,
        rationale: "auto_merge: LLM returned empty merge. Falling back to redirect.",
      };
    }

    const mergedAction = { ...proposedAction, [this.contentKey]: merged };
    const priorNames = priors.map((p) => p.agentId).join(", ");
    return {
      decision: MergeDecision.MERGED,
      mergedAction,
      rationale:
        `Auto-merged ${handle.agentId}'s draft with ${priors.length} prior ` +
        `agent(s) (${priorNames}) via LLM.`,
    };
  }
}

// ---------------------------------------------------------------------------
// Helpers (exported for tests)
// ---------------------------------------------------------------------------

async function fetchAllPriorContent(
  handle: IntentionHandleLike,
  conflicts: Conflict[],
  contentKey: string,
): Promise<PriorContent[]> {
  const intendMod = (await import("../intend.js").catch(() => null)) as unknown as
    | {
        getOrInitRuntime?: () => RuntimeLike;
        _getOrInitRuntime?: () => RuntimeLike;
      }
    | null;
  const getRt = intendMod?.getOrInitRuntime ?? intendMod?._getOrInitRuntime;
  if (!getRt) return [];

  const rt = getRt();
  if (!rt || !rt.bus) return [];

  const sessionId = handle.sessionId;
  const out: PriorContent[] = [];
  const seen = new Set<string>();

  for (const c of conflicts) {
    const cis = c.conflicting_intentions ?? [];
    for (const ci of cis) {
      const intId = ci.intention_id;
      const agentId = ci.agent_id ?? "unknown";
      if (!intId || seen.has(intId)) continue;
      seen.add(intId);
      const content = await readResolutionStateDiff(
        rt,
        intId,
        contentKey,
        sessionId,
      );
      if (content) {
        out.push({ agentId: String(agentId), intentionId: intId, content });
      }
    }
  }
  return out;
}

interface RuntimeLike {
  bus?: { redis?: { xrange: (stream: string, ...args: unknown[]) => Promise<Array<[string, Record<string, string>]>> } };
  agents?: Map<string, unknown> | Record<string, unknown>;
  mode?: string;
}

async function readResolutionStateDiff(
  rt: RuntimeLike,
  intentionId: string,
  contentKey: string,
  sessionId?: string,
): Promise<string | null> {
  const bus = rt.bus;
  const sid = sessionId || peekSessionFromRuntime(rt);
  if (!bus || !bus.redis || !sid) return null;

  const stream = `synapse:session:${sid}:events`;
  let entries: Array<[string, Record<string, string>]>;
  try {
    // ioredis xrange signature: redis.xrange(key, start, end, "COUNT", n)
    entries = await bus.redis.xrange(stream, "-", "+", "COUNT", 500);
  } catch {
    return null;
  }

  for (const [, fields] of entries) {
    const raw = fields["e"];
    if (!raw) continue;
    let env: Record<string, unknown>;
    try {
      env = JSON.parse(raw);
    } catch {
      continue;
    }
    if (env["type"] !== "RESOLUTION") continue;
    const payload = (env["payload"] as Record<string, unknown> | undefined) ?? {};
    if (payload["intention_id"] !== intentionId) continue;
    const sd = (payload["state_diff"] as Record<string, unknown> | undefined) ?? {};
    for (const k of [contentKey, "content", "output_preview", "output"]) {
      const v = sd[k];
      if (v !== undefined && v !== null && v !== "") {
        return String(v);
      }
    }
  }
  return null;
}

function peekSessionFromRuntime(rt: RuntimeLike): string | undefined {
  const agents = rt.agents;
  let keys: Iterable<string> = [];
  if (agents instanceof Map) {
    keys = agents.keys();
  } else if (agents && typeof agents === "object") {
    keys = Object.keys(agents);
  }
  for (const key of keys) {
    if (key.includes("::")) {
      return key.split("::", 2)[0];
    }
  }
  return process.env["SYNAPSE_SESSION_ID"];
}

interface LlmLike {
  generate?: (args: {
    messages: Array<{ role: string; content: string }>;
    max_tokens?: number;
    temperature?: number;
  }) => Promise<string>;
  _client?: {
    messages?: {
      create: (args: {
        model: string;
        max_tokens: number;
        messages: Array<{ role: string; content: string }>;
      }) => Promise<{ content?: Array<{ text?: string }> }>;
    };
    chat?: {
      completions?: {
        create: (args: {
          model: string;
          max_tokens: number;
          messages: Array<{ role: string; content: string }>;
          temperature?: number;
        }) => Promise<{ choices?: Array<{ message?: { content?: string } }> }>;
      };
    };
  };
  _model?: string;
}

async function llmMergeMulti(
  llm: LlmLike,
  args: {
    priors: PriorContent[];
    myAgent: string;
    myContent: string;
    scope: string[];
  },
): Promise<string> {
  const { priors, myAgent, myContent, scope } = args;
  const priorBlocks = priors
    .map((p) => `Agent ${p.agentId} wrote:\n\`\`\`\n${p.content}\n\`\`\``)
    .join("\n\n");
  const prompt =
    `Multiple AI agents wrote conflicting content for the same scope (${scope.join(", ")}).\n\n` +
    `PRIOR AGENT WRITES (in order, oldest first):\n\n` +
    `${priorBlocks}\n\n` +
    `NEW AGENT (${myAgent}) is about to write:\n\`\`\`\n${myContent}\n\`\`\`\n\n` +
    `Produce a single merged version that incorporates EVERY agent's intent.\n` +
    `  - Preserve fields/decisions from ALL agents — do not drop any contribution.\n` +
    `  - If two agents conflict semantically (e.g. different formulas), pick the\n` +
    `    one that looks more correct and add an inline comment.\n` +
    `  - Output only the merged content, no explanation, no markdown fences.`;
  return await llmCallText(llm, prompt);
}

async function llmCallText(llm: LlmLike, prompt: string): Promise<string> {
  const messages = [{ role: "user", content: prompt }];

  // Path 1: bridge adapters
  if (typeof llm.generate === "function") {
    try {
      const text = await llm.generate({
        messages,
        max_tokens: 1500,
        temperature: 0.0,
      });
      if (typeof text === "string" && text.trim()) return text.trim();
    } catch {
      // fall through to next path
    }
  }

  const client = llm._client;
  const model = llm._model ?? "claude-haiku-4-5-20251001";

  // Path 2: native Anthropic adapter
  if (client && client.messages && typeof client.messages.create === "function") {
    try {
      const msg = await client.messages.create({
        model,
        max_tokens: 1500,
        messages,
      });
      const blocks = msg?.content ?? [];
      const text = blocks[0]?.text ?? "";
      if (text && text.trim()) return text.trim();
    } catch {
      // fall through
    }
  }

  // Path 3: native OpenAI adapter
  if (
    client &&
    client.chat &&
    client.chat.completions &&
    typeof client.chat.completions.create === "function"
  ) {
    try {
      const resp = await client.chat.completions.create({
        model,
        max_tokens: 1500,
        messages,
        temperature: 0.0,
      });
      const text = resp?.choices?.[0]?.message?.content ?? "";
      if (text && text.trim()) return text.trim();
    } catch {
      // fall through
    }
  }

  return "";
}
