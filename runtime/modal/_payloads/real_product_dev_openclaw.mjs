// Real product-dev test for the OpenClaw integration.
//
// 3 OpenClaw "extensions" — each wrapped with wrapExtensionWithSynapse,
// each carrying a single `write_code` write-tool — get distinct agentIds
// (dev_a, dev_b, dev_c). Their tool handlers call real Anthropic Haiku to
// generate the implementation of a Python helper, then all three "write"
// to the SAME file path. defaultScope() maps `args.path` -> `repo.fs.<path>:w`
// so all three claim the same scope, and the L2 router catches the
// collision.
//
// Compares no_synapse vs with_synapse modes — same prompts, same model,
// same shared file.

import Anthropic from "@anthropic-ai/sdk";
import IORedis from "ioredis";
import {
  Bus,
  wrapExtensionWithSynapse,
} from "synapse-protocol";

const REDIS_URL = process.env.SYNAPSE_REDIS_URL || "redis://localhost:6379/0";
const SHARED_PATH = "src/utils/dedupe.py";

function makeWriteCodeExtension(client, agentId, prompt) {
  return {
    name: `dev-${agentId}`,
    tools: [
      {
        name: "write_code",
        description: `${agentId} writes the dedupe helper`,
        isWrite: true,
        handler: async (args) => {
          const msg = await client.messages.create({
            model: "claude-haiku-4-5-20251001",
            max_tokens: 250,
            messages: [{ role: "user", content: prompt }],
          });
          const text =
            msg.content?.[0]?.type === "text" ? msg.content[0].text : "";
          // simulate the actual write: capture first line of produced code
          return {
            agent: agentId,
            wrote_to: args.path,
            content: text,
            tokensIn: msg.usage?.input_tokens ?? 0,
            tokensOut: msg.usage?.output_tokens ?? 0,
          };
        },
      },
    ],
  };
}

const PROMPTS = {
  dev_a:
    "Write ONE Python function `dedupe(items: list) -> list` that removes " +
    "duplicates while PRESERVING order. Use a set to track seen items. " +
    "Output ONLY the function body (def + return), no explanation, no markdown.",
  dev_b:
    "Write ONE Python function `dedupe(items: list) -> list` that removes " +
    "duplicates. Use `list(dict.fromkeys(items))` because it preserves order " +
    "in Python 3.7+. Output ONLY the function body, no explanation, no markdown.",
  dev_c:
    "Write ONE Python function `dedupe(items: list) -> list` that removes " +
    "duplicates. Use a one-liner: sorted-set comprehension. Output ONLY " +
    "the function body, no explanation, no markdown.",
};

async function runScenario({ withSynapse, sessionId }) {
  const label = withSynapse ? "with_synapse" : "no_synapse";
  console.log(`\n--- mode: ${label} session=${sessionId} ---`);
  const t0 = Date.now();

  const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
  const agentIds = ["dev_a", "dev_b", "dev_c"];

  let bus = null;
  if (withSynapse) {
    bus = new Bus({ url: REDIS_URL });
    await bus.connect();
  }

  const extensions = agentIds.map((aid) => {
    const raw = makeWriteCodeExtension(client, aid, PROMPTS[aid]);
    if (!withSynapse) return raw;
    return wrapExtensionWithSynapse(raw, {
      bus,
      sessionId,
      agentId: aid,
      gateMs: 400,
      failOnConflict: false,
    });
  });

  // All 3 write to SAME path -> defaultScope hits same scope claim
  const results = await Promise.all(
    extensions.map((ext) =>
      ext.tools[0].handler({ path: SHARED_PATH }).catch((e) => ({
        error: String(e),
      }))
    )
  );

  // let coordinator/router catch up
  await new Promise((r) => setTimeout(r, 800));

  const redis = new IORedis(REDIS_URL);
  const stream = `synapse:session:${sessionId}:events`;
  const streamEntries = withSynapse
    ? await redis.xrange(stream, "-", "+", "COUNT", 200)
    : [];
  let conflictCount = 0;
  if (withSynapse) {
    for (const aid of agentIds) {
      const inbox = `synapse:agent:${aid}:inbox`;
      const ents = await redis.xrange(inbox, "-", "+", "COUNT", 50);
      for (const [, fields] of ents) {
        const eIdx = fields.indexOf("e");
        if (eIdx === -1) continue;
        try {
          const env = JSON.parse(fields[eIdx + 1]);
          if (env.type === "CONFLICT") conflictCount++;
        } catch {}
      }
    }
  }
  await redis.quit();

  // Detect the *implementation strategy* each agent chose, by regex on
  // the full content. Three orthogonal strategies — distinct = collision.
  const STRATEGY_PATTERNS = {
    "set-tracking": /\bseen\s*=\s*set\b/,
    "dict-fromkeys": /\bdict\.fromkeys\b/,
    "sorted-set-comp": /\bsorted\s*\(\s*set\b/,
  };
  const perAgentStrategy = results.map((r, i) => {
    if (r?.error) return `${agentIds[i]}->ERR`;
    const text = r?.content || "";
    const strategies = Object.entries(STRATEGY_PATTERNS)
      .filter(([, re]) => re.test(text))
      .map(([k]) => k);
    return `${agentIds[i]}->${strategies.join("|") || "?"}`;
  });
  const distinct = new Set(
    perAgentStrategy
      .map((s) => s.split("->")[1])
      .filter((x) => x && x !== "?" && x !== "ERR")
  );

  const tokensIn = results.reduce((s, r) => s + (r?.tokensIn ?? 0), 0);
  const tokensOut = results.reduce((s, r) => s + (r?.tokensOut ?? 0), 0);
  const elapsed = ((Date.now() - t0) / 1000).toFixed(1);

  console.log(`  elapsed:                 ${elapsed}s`);
  console.log(`  per-agent strategy:      ${perAgentStrategy.join(" | ")}`);
  console.log(`  distinct strategies:     ${[...distinct].join(", ")}`);
  console.log(`  total tokens in/out:     ${tokensIn}/${tokensOut}`);
  console.log(`  envelopes on stream:     ${streamEntries.length}`);
  console.log(`  CONFLICT envelopes:      ${conflictCount}`);

  if (bus) await bus.close();

  return {
    mode: label,
    session_id: sessionId,
    elapsed_seconds: parseFloat(elapsed),
    per_agent_strategy: perAgentStrategy,
    distinct_strategies: [...distinct],
    alignment: distinct.size === 1 ? 1.0 : 1.0 / Math.max(1, distinct.size),
    envelopes_on_stream: streamEntries.length,
    conflicts_detected: conflictCount,
    tokens_in: tokensIn,
    tokens_out: tokensOut,
    agent_results: results.map((r, i) => ({
      agent_id: agentIds[i],
      ok: !r?.error,
      excerpt: ((r?.content || r?.error || "") + "").slice(0, 160),
    })),
  };
}

async function main() {
  console.log("=== REAL OpenClaw product-dev test ===");

  const noSyn = await runScenario({
    withSynapse: false,
    sessionId: `openclaw_no_synapse_${Math.random().toString(36).slice(2, 10)}`,
  });
  const withSyn = await runScenario({
    withSynapse: true,
    sessionId: process.env.SYNAPSE_SESSION_ID,
  });

  console.log("\n--- summary ---");
  console.log(
    `  no_synapse:   distinct=${JSON.stringify(noSyn.distinct_strategies)} ` +
      `alignment=${noSyn.alignment.toFixed(2)} conflicts=${noSyn.conflicts_detected}`
  );
  console.log(
    `  with_synapse: distinct=${JSON.stringify(withSyn.distinct_strategies)} ` +
      `alignment=${withSyn.alignment.toFixed(2)} conflicts=${withSyn.conflicts_detected} ` +
      `envelopes=${withSyn.envelopes_on_stream}`
  );

  console.log("\n--- result.json ---");
  console.log(JSON.stringify({ no_synapse: noSyn, with_synapse: withSyn }, null, 2));
}

main().catch((e) => {
  console.error("fatal:", e);
  process.exit(1);
});
