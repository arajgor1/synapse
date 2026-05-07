/**
 * LLM-driven belief extraction from tool outputs.
 *
 * Ported from sdk-python/synapse/beliefs/extractor.py.
 *
 * When `emit_beliefs_from_tool_results=true`, every successful intend()
 * block runs this extractor on its tool's state_diff. The extractor calls
 * the user's BYO-LLM (via `setLlm`) and asks it to identify domain facts.
 *
 * The extractor is intentionally narrow: 0–3 facts per call, only when
 * there's strong textual evidence. Hallucinated beliefs poison divergence
 * detection, so we err on the side of fewer/no beliefs. If no LLM is
 * configured, extractor is a no-op and returns [].
 */

export interface FactExtraction {
  key: string;
  value: unknown;
  confidence: number;
  evidence?: string;
}

const PROMPT_TEMPLATE = `You are inspecting a tool call result from an AI agent.
Extract domain facts the agent now believes — DO NOT invent facts not present
in the output.

Tool: {tool_name}
Args: {tool_args}
Output: {output}

Return a JSON list of 0 to 3 facts. Each fact must have:
  - key: a stable, kebab-case identifier (e.g. "revenue_formula", "primary_key_column", "table_name").
        Use the SAME key two agents would naturally pick for the same fact.
  - value: the literal fact (string, number, list, etc).
  - confidence: 0.0 to 1.0
  - evidence: 1-line snippet from the output that supports the fact

Only emit facts you are CERTAIN are present in the output. If the output is
generic/uninteresting, return []. Output ONLY the JSON list, no other text.

Examples (illustrative — return only what's actually in the output):
  [{"key": "revenue_formula", "value": "qty * price", "confidence": 0.95, "evidence": "revenue = qty * price"}]
  [{"key": "primary_key", "value": "user_id", "confidence": 0.9, "evidence": "PRIMARY KEY (user_id)"}]
  []
`;

export interface ExtractBeliefsArgs {
  toolName: string;
  toolArgs: Record<string, unknown>;
  output: unknown;
  /** Override the configured LLM. Pass `null` to force no-op. */
  llm?: unknown;
  /** Cap on the output text we send to the LLM. */
  maxOutputChars?: number;
}

export async function extractBeliefsWithLLM(
  args: ExtractBeliefsArgs,
): Promise<FactExtraction[]> {
  const maxChars = args.maxOutputChars ?? 1500;

  let llm: unknown = args.llm;
  if (llm === undefined) {
    try {
      // Lazy import so test envs without llm/config don't fail at module load.
      const mod: { getInternalLlm?: () => unknown } = await import(
        "../llm/config.js"
      );
      llm = mod.getInternalLlm?.() ?? null;
    } catch {
      llm = null;
    }
  }
  if (llm === null || llm === undefined) return [];

  const textOutput = String(args.output ?? "").slice(0, maxChars);
  if (textOutput.trim() === "") return [];

  let argsJson: string;
  try {
    argsJson = JSON.stringify(args.toolArgs ?? {}, jsonReplacer).slice(0, 500);
  } catch {
    argsJson = String(args.toolArgs).slice(0, 500);
  }

  const prompt = PROMPT_TEMPLATE.replace("{tool_name}", args.toolName)
    .replace("{tool_args}", argsJson)
    .replace("{output}", textOutput);

  const text = await llmText(llm, prompt);
  if (!text) return [];
  return parseExtraction(text);
}

/** Replacer for unserializable values — fall back to String(v). */
function jsonReplacer(_k: string, v: unknown): unknown {
  if (typeof v === "bigint") return v.toString();
  if (typeof v === "function") return undefined;
  if (typeof v === "undefined") return null;
  return v;
}

/**
 * Parse LLM output into FactExtraction[]. Tolerant of code fences and
 * preamble. Caps at 3 facts (safety).
 *
 * Exported for tests under the name `parseExtraction`.
 */
export function parseExtraction(text: string): FactExtraction[] {
  let cleaned = text.trim();

  // Strip markdown code fences: ```json\n...\n``` or ```\n...\n```
  const fence = cleaned.match(/^```(?:json)?\s*([\s\S]*?)```\s*$/i);
  if (fence && fence[1] !== undefined) {
    cleaned = fence[1].trim();
  }

  // Find first '[' and last ']' to tolerate preamble/trailing text.
  const start = cleaned.indexOf("[");
  const end = cleaned.lastIndexOf("]");
  if (start === -1 || end === -1 || end < start) return [];

  let items: unknown;
  try {
    items = JSON.parse(cleaned.slice(start, end + 1));
  } catch {
    return [];
  }
  if (!Array.isArray(items)) return [];

  const out: FactExtraction[] = [];
  for (const it of items) {
    if (it === null || typeof it !== "object" || Array.isArray(it)) continue;
    const obj = it as Record<string, unknown>;
    if (!("key" in obj) || !("value" in obj)) continue;

    let confidence = 0.85;
    if ("confidence" in obj) {
      const raw = obj["confidence"];
      const n = typeof raw === "number" ? raw : Number(raw);
      if (!Number.isNaN(n)) confidence = n;
    }
    confidence = Math.max(0.0, Math.min(1.0, confidence));

    const evidenceRaw = obj["evidence"];
    const evidenceStr =
      evidenceRaw === undefined || evidenceRaw === null
        ? ""
        : String(evidenceRaw).slice(0, 200);

    const fact: FactExtraction = {
      key: String(obj["key"]).trim(),
      value: obj["value"],
      confidence,
    };
    if (evidenceStr.length > 0) fact.evidence = evidenceStr;
    out.push(fact);
  }

  return out.slice(0, 3); // safety cap
}

/**
 * Same multi-path LLM caller as policies' _llm_call_text in Python.
 *
 * Tries (in order):
 *   1. bridge `.generate({ messages, max_tokens, temperature })`
 *   2. native Anthropic via `_client.messages.create(...)`
 *   3. native OpenAI via `_client.chat.completions.create(...)`
 *
 * Returns "" on any failure.
 */
async function llmText(llm: unknown, prompt: string): Promise<string> {
  if (llm === null || typeof llm !== "object") return "";
  const messages = [{ role: "user", content: prompt }];
  const obj = llm as Record<string, unknown>;

  // Path 1: bridge .generate()
  const generate = obj["generate"];
  if (typeof generate === "function") {
    try {
      const res = await (generate as (a: {
        messages: { role: string; content: string }[];
        max_tokens: number;
        temperature: number;
      }) => Promise<unknown>).call(llm, {
        messages,
        max_tokens: 300,
        temperature: 0.0,
      });
      if (typeof res === "string" && res.trim()) return res.trim();
    } catch {
      // fall through
    }
  }

  const client = obj["_client"];
  const modelGuess = obj["_model"];
  const model =
    typeof modelGuess === "string" && modelGuess.length > 0
      ? modelGuess
      : "claude-haiku-4-5-20251001";

  if (client !== null && typeof client === "object") {
    const c = client as Record<string, unknown>;

    // Path 2: Anthropic-shaped
    const anthropicMessages = c["messages"];
    if (
      anthropicMessages !== null &&
      typeof anthropicMessages === "object" &&
      typeof (anthropicMessages as Record<string, unknown>)["create"] ===
        "function"
    ) {
      try {
        const create = (anthropicMessages as Record<string, unknown>)[
          "create"
        ] as (a: unknown) => Promise<unknown>;
        const msg = (await create.call(anthropicMessages, {
          model,
          max_tokens: 300,
          messages,
        })) as { content?: { text?: string }[] } | null | undefined;
        const blocks = msg && msg.content ? msg.content : [];
        const first = blocks[0];
        const text =
          first && typeof first.text === "string" ? first.text : "";
        if (text && text.trim()) return text.trim();
      } catch {
        // fall through
      }
    }

    // Path 3: OpenAI-shaped
    const chat = c["chat"];
    if (chat !== null && typeof chat === "object") {
      const completions = (chat as Record<string, unknown>)["completions"];
      if (
        completions !== null &&
        typeof completions === "object" &&
        typeof (completions as Record<string, unknown>)["create"] === "function"
      ) {
        try {
          const create = (completions as Record<string, unknown>)[
            "create"
          ] as (a: unknown) => Promise<unknown>;
          const resp = (await create.call(completions, {
            model,
            max_tokens: 300,
            messages,
            temperature: 0.0,
          })) as
            | { choices?: { message?: { content?: string } }[] }
            | null
            | undefined;
          const choices = resp && resp.choices ? resp.choices : [];
          const first = choices[0];
          const text =
            first && first.message && typeof first.message.content === "string"
              ? first.message.content
              : "";
          if (text && text.trim()) return text.trim();
        } catch {
          // fall through
        }
      }
    }
  }

  return "";
}
