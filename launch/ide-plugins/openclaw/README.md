# Synapse for OpenClaw

[OpenClaw](https://openclaw.ai) is a personal AI assistant with a serious
plugin/extension architecture (sponsored by OpenAI, GitHub, NVIDIA, Vercel —
100K+ stars). It coordinates agents across WhatsApp / Telegram / Slack /
Discord / Signal / iMessage / Teams / Matrix / Feishu / WeChat / 24+ channels.

Synapse plugs in at the **extension** layer — the same layer where every
OpenClaw tool/skill lives. Two integration paths, both shipped in
`synapse-protocol` (the TypeScript SDK).

## Why this matters for OpenClaw

OpenClaw's design encourages running **multiple specialised assistants** at once
(home, work, family) that may share resources (calendars, files, dialed-in skills,
the same Hermes agent backing them). When two assistants on different channels
both touch the same scope, classical OpenClaw has no built-in collision
detection. Synapse fills that gap without changing the channel surface.

## Path A: wrap an existing extension

Modify your OpenClaw extension's `plugin-registration.ts` to wrap the tool
registry through `wrapExtensionWithSynapse`:

```typescript
import { Bus } from "synapse-protocol";
import { wrapExtensionWithSynapse } from "synapse-protocol";

import { yourExistingExtension } from "./my-extension";

const bus = new Bus({ url: process.env.SYNAPSE_REDIS_URL });

export const synapseWrapped = wrapExtensionWithSynapse(yourExistingExtension, {
  bus,
  agentId: process.env.SYNAPSE_AGENT_ID ?? "openclaw",
  sessionId: process.env.SYNAPSE_SESSION_ID ?? "default",
});

// Register the WRAPPED extension instead of the original
openClawGateway.registerExtension(synapseWrapped);
```

Every write tool (`isWrite: true`, OR matched by `defaultScope` heuristics) now
runs through `synapse.intendWith()` — claims a scope, gets CONFLICTs back if
another OpenClaw extension or an external agent is touching the same scope,
and emits a RESOLUTION on completion.

Read-only tools bypass the gate (no overhead).

## Path B: standalone "synapse" extension

If you don't want to wrap your own extensions, register Synapse as its own
extension that exposes coordination as tools to OpenClaw skills:

```typescript
import { makeSynapseExtension } from "synapse-protocol";

openClawGateway.registerExtension(
  makeSynapseExtension({
    bus,
    agentId: "openclaw-main",
    sessionId: "user-default",
  }),
);
```

Now OpenClaw's `SOUL.md` skill authors can opt their custom tools into
coordination via `synapse_intention` / `synapse_resolution` / `synapse_conflicts`
without modifying the extension's wrapper.

## Multi-agent OpenClaw + Synapse

Real-world OpenClaw deployments often run alongside other coding-agent
flows (Hermes, Paperclip-managed Cursor / Codex / Claude). Synapse
coordinates across all of them — the same Redis bus + Postgres state
graph hosts intentions from every wrapped agent.

```bash
# In your OpenClaw deploy
SYNAPSE_REDIS_URL=redis://prod-redis/0 \
SYNAPSE_POSTGRES_DSN=postgresql://prod/synapse \
SYNAPSE_AGENT_ID=openclaw-home \
openclaw start

# In a separate Hermes session
SYNAPSE_REDIS_URL=redis://prod-redis/0 \
SYNAPSE_POSTGRES_DSN=postgresql://prod/synapse \
SYNAPSE_AGENT_ID=hermes-coder \
hermes-agent
```

Both processes coordinate via the shared Redis stream. CONFLICTs route to
the offending agent's inbox; the agent's framework handles the response
according to whatever MergePolicy you set.

## Verifying

The TypeScript SDK ships unit tests at
`sdk-typescript/src/frameworks/openclaw.test.ts` covering:

- write tool routing through `intendWith`
- read tool bypass
- multi-tool scope inference
- failure marking on tool errors

Plus an end-to-end real product-dev test in
`runtime/modal/_payloads/real_product_dev_openclaw.mjs` that runs 3 OpenClaw
extensions (`dev_a`, `dev_b`, `dev_c`) all wrapped with Synapse, all writing
to the same `src/utils/dedupe.py`, verifying CONFLICTs route correctly.

Result: see `bench/results/product_dev_real_openclaw_*.json` and
the [`bench/PUBLIC_BENCHMARK.md`](../../../bench/PUBLIC_BENCHMARK.md) Phase 7 section.

## Status

- ✅ TypeScript SDK adapter: `sdk-typescript/src/integrations/openclaw.ts`
- ✅ Unit tests: `sdk-typescript/src/frameworks/openclaw.test.ts`
- ✅ Real product-dev sandbox test (Modal, May 2026)
- ✅ Published to npm: `npm install synapse-protocol` (v0.2.8+)

## Reporting

If you hit issues integrating with OpenClaw v1.x or later, open an issue
at <https://github.com/arajgor1/synapse/issues> with your OpenClaw
version + the wrapped-extension config you tried.
