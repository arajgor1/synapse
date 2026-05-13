# `synapse-protocol` — TypeScript SDK

TypeScript / JavaScript client for the Synapse coordination protocol. Mirrors the Python SDK at `sdk-python/`.

> Pre-alpha. Surface: protocol types, envelope construction, Redis Streams bus client, Agent class, Mock inference adapter. Hosted/native adapters port over once the Python ones stabilize.

## Install

```bash
npm install synapse-protocol
# or
pnpm add synapse-protocol
```

## Quickstart

```ts
import { Agent, Bus, MockAdapter } from "synapse-protocol";

const bus = new Bus({ url: "redis://localhost:6379/0" });
await bus.connect();

const agent = new Agent({
  id: "agent_a",
  session: "my_session",
  backend: new MockAdapter(),
  subscribes: ["auth.*"],
  scopesOwned: ["auth.middleware"],
  bus,
});

const [intentionId, conflicts] = await agent.emitIntention({
  action: { tool: "edit_file", args: { path: "auth/middleware.ts" } },
  scope: ["auth.middleware:w"],
  expected_outcome: "Refactor middleware",
  blocking: true,
});

if (conflicts.length > 0) {
  console.log("Pivot needed:", conflicts[0]?.suggested_resolution);
} else {
  // do the work
  await agent.emitResolution({ intentionId, outcome: "success" });
}

await bus.close();
```

## What's in this version

| Module | Status |
|---|---|
| `types` | All 8 message payloads + envelope + capabilities + tenant context |
| `envelope` | `makeEnvelope()` ULID generator, `isUlid()` validator |
| `bus` | Redis Streams client (publish, drainInbox, ensureGroup) via ioredis |
| `agent` | `Agent` class — emitIntention / emitResolution / emitBelief / emitBlock, waitForSignal |
| `adapters/base` | `InferenceAdapter` interface, StreamHandle, Token, error types, `TenantViolation` |
| `adapters/mock` | Mock adapter with multi-tenant `request_id` isolation by default |

## Multi-tenant isolation

The Mock adapter (and any future adapter implementing `multi_tenant_isolation: "request_id"`) rejects cross-tenant access on any in-flight `request_id`:

```ts
const owner = { tenant_id: "acme", agent_id: "a1", session_id: "s1" };
const handle = await adapter.startStream([], { tenant: owner });

// An attacker with a different tenant context can't read this stream:
const attacker = { ...handle, tenant: { tenant_id: "evilcorp" } };
for await (const t of adapter.readTokens(attacker)) {
  // throws TenantViolation before yielding
}
```

## Test

```bash
npm install
npm test         # vitest run
npm run typecheck
```

12 tests across envelope construction, ULID validation, mock streaming, inject-and-continue, partial preservation on cancel, and multi-tenant isolation.

## Roadmap

| Item | Phase |
|---|---|
| Hosted adapters (Anthropic, OpenAI, Gemini) | v0.2 |
| Local-API (Ollama) | v0.2 |
| Native adapters (vLLM-via-Modal RPC) | v0.3 |
| Framework integrations (LangChain, Mastra, Vercel AI SDK) | v0.3 |
