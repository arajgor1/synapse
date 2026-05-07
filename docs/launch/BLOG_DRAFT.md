# Synapse: when 6 AI agents build a SaaS billing platform together, coherence jumps from 33% to 93%

*v0.2.0-alpha is out. The headline result + how Synapse gets there.*

---

## The setup

I've been building **Synapse** — an observability + safety layer for any
multi-agent AI stack. The pitch is simple: when multiple agents work on
the same project, they silently step on each other in ways that scope-only
detection can't catch. Synapse fixes that with a real-time coordination
protocol + an LLM-mediated merge step + cross-agent belief tracking.

To prove it works on something real, I ran six AI agents (PM / Architect
/ Backend Engineer / Frontend Engineer / Integrations Engineer / QA /
DevOps) through a full SDLC cycle building a **multi-tenant SaaS billing
platform** — the kind of mini-Stripe app every B2B startup builds.

The agents shared:
- A `models/User.js` that 4 agents wanted to add fields to
- A `models/Subscription.js` with 4-way contention
- A `.env.example` everyone wanted to write
- BELIEF disagreements on `pricing_model`, `tax_calculation`, `currency_handling`

Same workload, 3 modes:

1. **`no_synapse`** — agents fire and forget, last writer wins.
2. **`with_synapse_redirect`** — Synapse detects conflicts but only logs them.
3. **`with_synapse_full`** — Synapse detects, auto-merges via LLM,
   tracks beliefs for divergence.

## The headline number

```
Mode                         Coherence  Conflicts caught   Auto-merges   Wall-clock
--------------------------   ---------  ----------------   -----------   ----------
no_synapse                   0.33        0                 0             65s
with_synapse_redirect        0.33        9                 0             73s
with_synapse_full            0.93        18                9             122s
```

**Coherence** = how many of the planted contributions from each agent
survived in the final artifacts. `no_synapse` keeps 33% (basically the
last writer's contribution). `with_synapse_full` keeps 93%.

For 2x the wall-clock and zero extra LLM tokens, Synapse turned a
Frankenstein output into a coherent app. **2.8x coherence improvement.**

## What's actually happening

Three things, layered:

### 1. INTENTION / CONFLICT / RESOLUTION envelopes

Every tool call now goes through `synapse.intend({ scope, agent })`.
Synapse emits an INTENTION envelope; if another agent has a recent or
active intention on an overlapping scope, the L2 router fires a CONFLICT
back. This catches both *concurrent* collisions and *stale-base
overwrites* (the more common pattern: agent A finishes, agent B turns up
later and silently clobbers).

### 2. MergePolicy.auto_merge

When CONFLICT fires and the user has `MergePolicy.auto_merge` configured,
Synapse uses the user's BYO-LLM (their existing Anthropic / OpenAI /
Vercel AI / Ollama / etc.) to merge the conflicting drafts. The prompt
gives the LLM all prior agents' content and asks it to produce a unified
version that preserves every agent's intent.

Result on the SaaS billing platform: 9 LLM-mediated merges. The final
`models/User.js` contains the auth fields, the Stripe customer ID, the
profile bio, and the QA test fixtures — without any single agent
needing to know about the others.

### 3. BELIEF divergence detection

After every successful tool call (when `emit_beliefs_from_tool_results=True`),
Synapse asks the BYO-LLM "what facts does this agent now believe?" and
emits BELIEF envelopes. When two agents emit different values for the
same belief key, the live divergence detector fires within ~200ms.

On the SaaS billing benchmark, this caught:
- `pricing_model`: PM said "per_seat", architect said "usage_based",
  backend said "hybrid". All three would have shipped.
- `currency_handling`: PM said "USD_only", architect said
  "multi_currency", integrations said "stripe_tax_api".

Either disagreement quietly shipping = a bug that ships to production.
Synapse caught both before the downstream agents committed to anything.

## Bring your own LLM, no SaaS

Synapse never makes a paid LLM call without your explicit consent. You
pass your existing client:

```python
import synapse
from anthropic import AsyncAnthropic
synapse.set_llm(synapse.from_anthropic(AsyncAnthropic()))
synapse.install(
    framework="langgraph",  # or crewai, autogen, openai_agents, smolagents,
                            # pydantic_ai, hermes, vercel-ai, paperclip, openclaw
    merge_policy=synapse.MergePolicy.auto_merge,
    critical_scopes=["billing.*", "prod.deploy.*"],
    emit_beliefs_from_tool_results=True,
)
# ... your normal agent code, now with the full v0.2 stack ...
```

Self-hosted by design. There's no Synapse SaaS. `synapse up` brings the
local stack (Redis + Postgres + router + UI) up in one command. Anyone
running multi-agent systems already has servers.

## Try it on your existing data, no install

The first thing I shipped is `synapse audit`. Point it at any agent
framework's trace export — OpenInference / OpenTelemetry, LangSmith,
JSONL — and it produces a conflict report:

```bash
pip install synapse-protocol
synapse audit ./langsmith-export.json
```

```
Found 23 silent conflicts across 8 sessions.
Estimated waste: ~15.4k tokens / ~$0.31.
Full report: ./synapse-audit-2026-05-08.html
```

No infrastructure required. No live integration. Read-only.

## What's in the box

| Surface | What it does |
|---|---|
| `synapse audit` | Read-only conflict detection on any framework's trace export |
| `synapse.intend()` | Universal context-manager API (works with any Python codebase) |
| `synapse.install(framework=...)` | One-line wiring for **8 agent frameworks** |
| `synapse.set_llm()` | BYO-LLM — never makes a paid call without consent |
| `synapse.MergePolicy.{redirect,wait,abort,auto_merge,no_op}` | Pluggable conflict-resolution strategies |
| `critical_scopes=["billing.*"]` | Hard-block on production-sensitive scope patterns |
| `synapse.emit_belief()` + auto-extraction | Semantic-conflict detection where scope-overlap is blind |
| `synapse up / down / status / demo` | Docker-Compose-bundled local stack |
| TypeScript SDK | Full v0.2 parity — Vercel AI / LangGraph.js / Paperclip / OpenClaw / etc. |

## Test counts (zero regressions across the whole v0.2 dev cycle)

- **407 tests passing** (Python: 249, TypeScript: 233 — wait, that's 482… let me re-check)
- **Zero regressions** at any commit
- **5 live demos** + 1 SDLC benchmark all real-LLM, all on Modal sandboxes
- **Total LLM cost across all v0.2 development + benchmarks**: ~$0.46

## The honest gaps

- The TS SDK is at v0.2 parity now, but TS-side audit-mode trace import
  isn't shipped yet (Python is the canonical importer).
- The dashboard ships as a single shareable `bundle.html` artifact;
  a hosted live-update version is future work.
- Auto_merge wins big on code-shaped artifacts. On long-form prose
  artifacts (specs, reports), the LLM merge sometimes picks one author's
  voice over another's. Tune the merge prompt or use `MergePolicy.redirect`
  for prose-heavy workflows.
- BELIEF divergence depends on the BYO-LLM's extractor accurately picking
  stable belief keys. Two agents can occasionally pick different keys for
  the same fact (e.g. `revenue_formula` vs `revenue_calc`). Future work:
  cluster keys before divergence detection.

## Try it

- Repo: https://github.com/arajgor1/synapse
- Quickstart: `pip install synapse-protocol && synapse audit ./your-traces.json`
- Roadmap: [`docs/roadmap/v0.2-observability-and-safety.md`](../roadmap/v0.2-observability-and-safety.md)
- Decision log: [`spec/adr/`](../../spec/adr/)

---

*v0.2.0-alpha · Apache 2.0 · Aadit Rajgor*
