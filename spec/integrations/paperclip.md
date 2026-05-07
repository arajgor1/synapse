# Paperclip AI integration

Paperclip ([github.com/paperclipai/paperclip](https://github.com/paperclipai/paperclip)) is an explicit **multi-agent coordination framework** by [@dotta](https://twitter.com/dotta) — agents-as-employees with org charts, budgets, and goals. Its `adapter-plugin.md` exposes a mutable adapter registry (`registerServerAdapter`, `unregisterServerAdapter`, `requireServerAdapter`) that's perfect for Synapse to plug into.

## TL;DR for Paperclip users

```ts
import { registerServerAdapter } from "paperclip/server/adapters/registry";
import { wrapAdapterWithSynapse } from "@synapse-protocol/sdk/integrations/paperclip";
import { Bus } from "@synapse-protocol/sdk";
import { anthropicAdapter } from "paperclip/server/adapters/anthropic";

const bus = new Bus({ url: process.env.SYNAPSE_REDIS_URL! });
await bus.connect();

const synapseAnthropic = wrapAdapterWithSynapse(anthropicAdapter, {
  bus,
  sessionId: process.env.PAPERCLIP_COMPANY_ID!,
  scopeFromTask: (task) => [`paperclip.task:${task.id}:w`],
});

registerServerAdapter(synapseAnthropic);
```

Now every Paperclip task that flows through this adapter:

1. Emits a Synapse `INTENTION` before invocation, with scope derived from the task
2. Waits the configured gate window (default 50ms) for `CONFLICT` signals
3. If a conflict is detected, returns a Paperclip `AdapterError` of kind `synapse_conflict` so the existing escalation path handles the pivot
4. On clean execution, runs the inner adapter and emits `RESOLUTION` + a `COST_REPORT` envelope with token spend

## Why this matters for Paperclip

Paperclip's own thesis (paraphrased from their docs):
> *"The hard problem in multi-agent AI isn't making individual agents smarter. It's making them coordinate."*

Paperclip solves coordination at the **org level** (reporting structures, budgets, escalation paths). Synapse solves it at the **operational level** (intention broadcasting, scope conflict detection, mid-stream pivots). They compose:

- **Paperclip's org chart** says *"Engineering reports to CTO; Marketing reports to CMO; Engineering owns the codebase scope."*
- **Synapse's protocol** enforces that ownership at runtime: when two engineering agents both claim `repo.auth.middleware:w`, the conflict surfaces in milliseconds.

## Configuration

```ts
wrapAdapterWithSynapse(innerAdapter, {
  bus: Bus,                       // Required — connected Synapse bus
  sessionId: string,              // Required — usually companyId

  // Optional
  scopeFromTask: (task) => string[],   // default: [`paperclip.task:${task.id}:w`]
  failOnConflict: true,                // default: true
  gateMs: 50,                          // default: 50
  synapseBackend: InferenceAdapter,    // default: MockAdapter
});
```

`scopeFromTask` is where you express your org-chart's resource model. Examples:

```ts
// Map by department
(task) => [`dept.${task.metadata?.department}:w`]

// Lock a specific resource path
(task) => [`paperclip.resource:${task.metadata?.resource}:w`]

// Multiple scopes — task touches engineering AND marketing
(task) => [
  `dept.engineering.${task.metadata?.feature}:w`,
  `dept.marketing.${task.metadata?.campaign}:r`,  // read-only
]
```

## Verification

`sdk-typescript/src/integrations/paperclip.test.ts` covers:

- ✅ INTENTION + RESOLUTION + COST_REPORT emitted for clean dispatch
- ✅ CONFLICT path surfaces as AdapterError on the response
- ✅ `scopeFromTask` callback drives scope claims
- ✅ Failure outcome propagates to RESOLUTION
- ✅ Mock convenience constructor works

5/5 tests passing in vitest.

## Live smoke (Modal sandbox)

Inline-mock smoke run (full Paperclip is a 100MB+ pnpm tree — out of scope for the cheap sandbox; the integration code is identical to what the unit tests exercise):

```
[paperclip] inner response: { text: 'hello', tokensIn: 50, tokensOut: 25 }
[paperclip] envelopes published:
  INTENTION   agent=engineer_a scope=['paperclip.task:T1:w']
  RESOLUTION  agent=engineer_a outcome=success
  COST_REPORT tokens=75
```

For end-to-end validation against a real Paperclip instance, follow the README quickstart in this doc — it works with their production server adapter registry, no patches required.
