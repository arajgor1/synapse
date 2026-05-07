// Real product-dev test for the Paperclip integration.
//
// 3 "employees" (engineer_a, engineer_b, engineer_c) each get a Paperclip task
// to design the SAME Todo REST endpoint. Each task uses the *real* Paperclip
// adapter shape (PaperclipAdapter) wrapped with wrapAdapterWithSynapse, and
// each calls real Anthropic Haiku 4.5. They all claim the same shared scope
// (`paperclip.shared:todo_api:w`), so an honest no_synapse run silently
// produces three divergent designs while a with_synapse run catches the
// collision.
//
// Comparison: no_synapse vs with_synapse modes. Metrics:
//   - distinct route paths each agent picked
//   - envelopes on bus stream
//   - CONFLICTs delivered to per-agent inboxes (Synapse mode)
//   - intentions persisted (via the Python state-mirror sidecar)
//   - real Anthropic token usage

import Anthropic from "@anthropic-ai/sdk";
import IORedis from "ioredis";
import {
  Bus,
  wrapAdapterWithSynapse,
} from "@synapse-protocol/sdk";

const REDIS_URL = process.env.SYNAPSE_REDIS_URL || "redis://localhost:6379/0";
const SHARED_SCOPE = "paperclip.shared:todo_api:w";

// Real Paperclip-shape adapter that calls Anthropic
function makeRealAnthropicAdapter(client) {
  return {
    type: "anthropic-real",
    async invoke(req) {
      const msg = await client.messages.create({
        model: "claude-haiku-4-5-20251001",
        max_tokens: 250,
        messages: [{ role: "user", content: req.prompt }],
      });
      const text = msg.content?.[0]?.type === "text" ? msg.content[0].text : "";
      return {
        text,
        tokensIn: msg.usage?.input_tokens ?? 0,
        tokensOut: msg.usage?.output_tokens ?? 0,
      };
    },
  };
}

const PROMPTS = {
  engineer_a:
    "You are engineer A. Define ONE FastAPI Todo endpoint URL path (just the route, " +
    "no implementation). Use plural, snake_case. Output ONLY the literal route line " +
    'in the form `@app.post("/<path>")`, nothing else. Pick a name like /tasks/ or /todos/ etc.',
  engineer_b:
    "You are engineer B. Define ONE FastAPI Todo endpoint URL path (just the route, " +
    "no implementation). Use plural. Output ONLY the literal route line in the form " +
    '`@app.post("/<path>")`, nothing else. Use a different name from your colleagues.',
  engineer_c:
    "You are engineer C. Define ONE FastAPI Todo endpoint URL path (just the route, " +
    "no implementation). Output ONLY the literal route line in the form " +
    '`@app.post("/<path>")`, nothing else. Pick a fresh, distinct name.',
};

async function runScenario({ withSynapse, sessionId }) {
  const label = withSynapse ? "with_synapse" : "no_synapse";
  console.log(`\n--- mode: ${label} session=${sessionId} ---`);

  const t0 = Date.now();

  const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
  const innerAdapter = makeRealAnthropicAdapter(client);

  let bus = null;
  let adapter = innerAdapter;
  if (withSynapse) {
    bus = new Bus({ url: REDIS_URL });
    await bus.connect();
    adapter = wrapAdapterWithSynapse(innerAdapter, {
      bus,
      sessionId,
      // All three agents claim the same shared scope -> collision
      scopeFromTask: (_t) => [SHARED_SCOPE],
      gateMs: 400,
      failOnConflict: false, // log+continue so we can measure CONFLICTs delivered
    });
  }

  // 3 parallel Paperclip-style tasks
  const agentIds = ["engineer_a", "engineer_b", "engineer_c"];
  const tasks = agentIds.map((aid) => ({
    task: { id: `t_${aid}`, agentId: aid, description: `route for ${aid}` },
    prompt: PROMPTS[aid],
  }));

  const results = await Promise.all(
    tasks.map((req) =>
      adapter.invoke(req).catch((e) => ({ error: String(e) }))
    )
  );

  // let coordinator/router catch up
  await new Promise((r) => setTimeout(r, 800));

  // Inspect what landed
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
      // Each entry: [entryId, [field1, value1, field2, value2, ...]]
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

  // Extract route picked by each agent
  const ROUTE_RE = /@app\.post\("([^"]+)"\)/;
  const perAgentRoute = results.map((r, i) => {
    if (r?.error) return `ERR(${agentIds[i]})`;
    const m = (r?.text || "").match(ROUTE_RE);
    return m ? `${agentIds[i]}->${m[1]}` : `${agentIds[i]}->?`;
  });
  const distinctRoutes = new Set(
    perAgentRoute
      .map((s) => s.split("->")[1])
      .filter((x) => x && x !== "?")
  );

  const tokensIn = results.reduce((s, r) => s + (r?.tokensIn ?? 0), 0);
  const tokensOut = results.reduce((s, r) => s + (r?.tokensOut ?? 0), 0);
  const elapsed = ((Date.now() - t0) / 1000).toFixed(1);

  console.log(`  elapsed:                 ${elapsed}s`);
  console.log(`  per-agent route:         ${perAgentRoute.join(" | ")}`);
  console.log(`  distinct routes:         ${[...distinctRoutes].join(", ")}`);
  console.log(`  total tokens in/out:     ${tokensIn}/${tokensOut}`);
  console.log(`  envelopes on stream:     ${streamEntries.length}`);
  console.log(`  CONFLICT envelopes:      ${conflictCount}`);

  if (bus) await bus.close();

  return {
    mode: label,
    session_id: sessionId,
    elapsed_seconds: parseFloat(elapsed),
    per_agent_route: perAgentRoute,
    distinct_routes: [...distinctRoutes],
    alignment: distinctRoutes.size === 1 ? 1.0 : 1.0 / Math.max(1, distinctRoutes.size),
    envelopes_on_stream: streamEntries.length,
    conflicts_detected: conflictCount,
    tokens_in: tokensIn,
    tokens_out: tokensOut,
    agent_results: results.map((r, i) => ({
      agent_id: agentIds[i],
      ok: !r?.error,
      excerpt: (r?.text || r?.error || "").slice(0, 120),
    })),
  };
}

async function main() {
  console.log("=== REAL Paperclip product-dev test ===");

  const noSyn = await runScenario({
    withSynapse: false,
    sessionId: `paperclip_no_synapse_${Math.random().toString(36).slice(2, 10)}`,
  });
  const withSyn = await runScenario({
    withSynapse: true,
    sessionId: process.env.SYNAPSE_SESSION_ID,
  });

  console.log("\n--- summary ---");
  console.log(
    `  no_synapse:   distinct=${JSON.stringify(noSyn.distinct_routes)} ` +
      `alignment=${noSyn.alignment.toFixed(2)} conflicts=${noSyn.conflicts_detected}`
  );
  console.log(
    `  with_synapse: distinct=${JSON.stringify(withSyn.distinct_routes)} ` +
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
