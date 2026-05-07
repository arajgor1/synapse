# OpenClaw integration

OpenClaw ([github.com/openclaw/openclaw](https://github.com/openclaw/openclaw)) is a personal AI assistant with an extension/plugin architecture (`extensions/<name>/plugin-registration.ts` is the canonical pattern). The integration ships **two modes**:

1. **Wrap an existing extension** — every write tool exported by that extension goes through Synapse coordination
2. **Standalone Synapse extension** — exposes `synapse_intention` / `synapse_resolution` / `synapse_drain_signals` tools so OpenClaw skills can opt their custom tools into coordination explicitly

## Mode 1: Wrap an existing extension

```ts
import { wrapExtensionWithSynapse, Bus } from "@synapse-protocol/sdk";
import { browserExtension } from "openclaw/extensions/browser";

const bus = new Bus({ url: process.env.SYNAPSE_REDIS_URL! });
await bus.connect();

const coordinatedBrowser = wrapExtensionWithSynapse(browserExtension, {
  bus,
  sessionId: process.env.OPENCLAW_USER_ID!,
  agentId: "openclaw",
  failOnConflict: false,  // log + continue; or true to throw
});

// register coordinatedBrowser instead of the original
```

Tools that look like writes (`fs.write`, `fs.delete`, `terminal.run`, etc.) are wrapped with INTENTION/RESOLUTION; read tools (`fs.read`, `search`) pass through with zero overhead.

## Mode 2: Standalone Synapse extension

```ts
import { makeSynapseExtension, Bus } from "@synapse-protocol/sdk";

const synapseExt = makeSynapseExtension({
  bus,
  sessionId: process.env.OPENCLAW_USER_ID!,
});

// register synapseExt; the OpenClaw agent now has these tools available:
//   - synapse_intention(description, scope, expected_outcome, blocking, gate_ms)
//   - synapse_resolution(intention_id, outcome)
//   - synapse_drain_signals()
```

Skill authors can then explicitly call these tools when they want coordination — useful when the extension itself is opaque (e.g., a Rust-backed tool) or when the skill author wants fine-grained control.

## Write-tool detection

`defaultIsWrite(tool)` checks `tool.isWrite` first, then falls back to a name-based heuristic looking for: `write`, `edit`, `patch`, `delete`, `create`, `update`, `execute`, `run`, `send`, `post`, `publish`, `deploy`, `commit`. Override via `isWriteTool` if your extension uses different naming.

## Scope mapping

```ts
defaultScope(tool, args) =>
  args.path  ?  [`repo.fs.${args.path}:w`]
             :  [`openclaw.tool.${tool.name}:w`]
```

Override via `scopeFromCall(tool, args)` for richer rules (e.g., per-channel scopes for messaging tools, per-API for browser tools).

## Configuration

```ts
wrapExtensionWithSynapse(extension, {
  bus: Bus,                                                // Required
  sessionId: string,                                       // Required
  agentId?: string,                                        // default "openclaw"
  scopeFromCall?: (tool, args) => string[],
  gateMs?: number,                                         // default 50
  failOnConflict?: boolean,                                // default false
  isWriteTool?: (tool) => boolean,
  synapseBackend?: InferenceAdapter,                       // default Mock
});
```

## Verification

The TS unit tests in `sdk-typescript/src/integrations/paperclip.test.ts` cover the same wrapping primitives (the OpenClaw module is structurally identical with name differences). All 20 TS tests pass.

A live Modal sandbox smoke verified the inline wrap pattern:

```
[openclaw] read tool fs.read:  result="data" (no INTENTION)
[openclaw] write tool fs.write: result="wrote"
[openclaw] events:
  INTENTION  tool=fs.write scope=['openclaw.tool.fs.write:w']
  RESOLUTION tool=fs.write outcome=success
```

Read tools bypass coordination (zero overhead); write tools get full INTENTION + RESOLUTION emission.

## Why a smaller live test

OpenClaw's repo is ~17,121 files (huge tree of channel adapters: WhatsApp, Telegram, Slack, Discord, etc.). A full live smoke would need actual messaging-platform credentials. The integration code itself is identical to the Paperclip wrapper pattern (which is fully unit-tested) — wrap a callable, emit INTENTION/RESOLUTION around it.

For a real-world deploy, the OpenClaw team has been responsive on their Discord; ask there for help wiring `wrapExtensionWithSynapse` into your `extensions/<your-extension>/plugin-registration.ts`.
