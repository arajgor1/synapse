# Synapse

> **The safety layer for multi-agent AI systems.**
> Audit existing logs for silent collisions, prevent them live, and resolve them with your own LLM.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Version: v0.2.1-alpha](https://img.shields.io/badge/Version-v0.2.1--alpha-blue.svg)](#status)
[![Spec: v1.0](https://img.shields.io/badge/Spec-v1.0-green.svg)](spec/protocol-v1.0/)
[![Tests](https://img.shields.io/badge/tests-482%20passing-brightgreen.svg)](#tests)

---

## What Synapse is for

When AI agents share state — the same repo, the same database, the same customer — they collide. Two agents rewrite the same file with different ideas. Three agents independently decide on three different revenue formulas. The last writer wins, contributions vanish silently, and nobody notices until production breaks.

Synapse is the open-source protocol + libraries that **detect, audit, and resolve those collisions** before they corrupt your output.

It sits next to — not against — the observability tools you already use. The collisions that LangSmith / Arize Phoenix / Langfuse log, Synapse catches and resolves.

## What Synapse is NOT

- Not another LLM-call observability tool. Use [LangSmith](https://www.langchain.com/langsmith) / [Phoenix](https://phoenix.arize.com) / [Langfuse](https://langfuse.com) for traces and eval. We sit on top.
- Not a cross-vendor agent interop standard. [A2A](https://github.com/a2aproject/A2A) covers that.
- Not a tool-access standard. [MCP](https://modelcontextprotocol.io) covers that.
- Not a new agent framework. We wrap the ones you already use ([LangGraph](https://github.com/langchain-ai/langgraph), [CrewAI](https://github.com/crewAIInc/crewAI), [AutoGen](https://github.com/microsoft/autogen), [Vercel AI SDK](https://sdk.vercel.ai), and 7 more).

## Three layers, one product

```
┌────────────────────────────────────────────────────────────┐
│  AUDIT (the wedge)                                         │
│    synapse audit ./traces.json                             │
│  → free, no install, reads OpenInference / LangSmith / JSONL │
│  → output: HTML report listing every silent collision      │
│    in your existing logs                                   │
└─────────────────────────┬──────────────────────────────────┘
                          ▼ once you see the problem
┌────────────────────────────────────────────────────────────┐
│  STANDARD + LIBRARY (the protocol)                         │
│    synapse-protocol v1.0 — open spec + Python + TS SDKs    │
│  → 11 framework adapters: LangGraph, CrewAI, AutoGen,      │
│    OpenAI Agents SDK, Pydantic AI, smolagents, Vercel AI   │
│    SDK, LangGraph.js, Hermes, Paperclip, OpenClaw          │
│  → BYO-LLM, self-hosted, Apache 2.0                        │
└─────────────────────────┬──────────────────────────────────┘
                          ▼ wire it in, get
┌────────────────────────────────────────────────────────────┐
│  SAFETY (the value-add)                                    │
│  → MergePolicy.auto_merge — LLM-mediated reconciliation    │
│  → critical_scopes — hard-block on production paths        │
│  → BELIEF divergence — catches semantic conflicts          │
│    that file-overlap detection misses                      │
└────────────────────────────────────────────────────────────┘
```

## 60-second hello-world

### 1. Audit your existing logs (no infrastructure needed)

```bash
pip install synapse-protocol
synapse audit ./your-langsmith-export.json
```

```
Found 23 silent conflicts across 8 sessions.
Estimated waste: ~15.4k tokens / ~$0.31.
Full report: ./synapse-audit-2026-05-08.html
```

The audit CLI reads OpenInference OTel JSON, LangSmith export JSON, or generic JSONL. **No Redis. No Postgres. No live integration.** Just point it at trace data you already have.

### 2. Wire it into your live stack (3 lines)

Once you see the problem, install the live runtime and add 3 lines to your existing agent code:

```bash
pip install 'synapse-protocol[live]'   # adds Redis + Postgres clients
synapse up                              # starts local stack via Docker Compose
```

```python
import synapse
from anthropic import AsyncAnthropic

synapse.set_llm(synapse.from_anthropic(AsyncAnthropic()))   # bring your own LLM
synapse.install(framework="langgraph")                      # one of: langgraph, crewai,
                                                            # autogen, openai_agents,
                                                            # pydantic_ai, smolagents,
                                                            # vercel-ai, hermes, ...
# ... your normal agent code, now with safety semantics ...
```

### 3. Turn on auto-merge for the case that matters

```python
synapse.install(
    framework="langgraph",
    merge_policy=synapse.MergePolicy.auto_merge,   # LLM-mediated merge on collision
    critical_scopes=["billing.*", "prod.deploy.*"],  # hard-block on these scopes
    emit_beliefs_from_tool_results=True,             # catch semantic conflicts
)
```

That's the entire surface. **Bring your own LLM**, self-hosted by design, never auto-charges your account.

## Where Synapse helps (and where it doesn't)

Honest scope from real benchmark runs:

| Pattern | Synapse value |
|---|---|
| **Multi-team / multi-orchestrator** sharing a codebase | ✅ **Real safety.** SDLC benchmark: coherence 0.33 → 0.93 with auto_merge. |
| **Sub-agent spawning** (Hermes-style, swarm patterns) | ✅ **Real safety.** Children don't know about each other. |
| **Audit existing trace data** for past collisions | ✅ **Real audit.** No false positives, runs without infra. |
| **Hierarchical orchestrator + workers** (LangGraph supervisor, CrewAI hierarchy) | ⚠️ **Mostly observability.** A competent orchestrator pre-deconflicts; Synapse runs cleanly but adds little detection value. |
| **Single agent** | ❌ **Pure overhead.** Synapse correctly does nothing. Don't install it. |

We had to learn this empirically — see [`bench/results/v02_autonomous_*/FINDINGS.md`](bench/results/) for the autonomous-test write-up that disconfirmed the early "any multi-agent system" pitch.

## Installs

| Install | What you get | Heavy deps |
|---|---|---|
| `pip install synapse-protocol` | `synapse audit` CLI + read-only audit pipeline | none (pydantic + jsonschema only) |
| `pip install 'synapse-protocol[live]'` | Above + Bus + StateGraph + framework adapters + dashboard | Redis client, asyncpg, python-ulid |
| `pip install 'synapse-protocol[live,hosted]'` | Above + Anthropic / OpenAI / Gemini bridges | + provider SDKs |
| `pip install 'synapse-protocol[all]'` | Everything | all of the above |

```bash
# JavaScript / TypeScript ecosystem
npm install @synapse-protocol/sdk
```

## Frameworks supported (11 adapters across Python + TypeScript)

| Framework | Python | TypeScript |
|---|---|---|
| LangGraph | ✅ | ✅ (LangGraph.js) |
| CrewAI | ✅ | — |
| AutoGen (0.4+) | ✅ | — |
| OpenAI Agents SDK | ✅ | — |
| Pydantic AI | ✅ | — |
| smolagents | ✅ | — |
| Vercel AI SDK | — | ✅ |
| Hermes Agent | ✅ | — |
| Paperclip AI | — | ✅ |
| OpenClaw | — | ✅ |

Don't see yours? `synapse.intend()` (Python) and `synapse.intendWith()` (TypeScript) are universal context-manager APIs that work in *any* codebase.

## Status

**v0.2.1-alpha — feature-complete, launch-ready, tagged.**

- Protocol spec: [`spec/protocol-v1.0/`](spec/protocol-v1.0/) (frozen at v1.0)
- Python SDK: 249 tests passing
- TypeScript SDK: 233 tests passing
- 6 live benchmarks in [`bench/benchmarks.md`](bench/benchmarks.md), all real-LLM
- Architecture decisions in [`spec/adr/`](spec/adr/)
- Roadmap: [`docs/roadmap/v0.2-observability-and-safety.md`](docs/roadmap/v0.2-observability-and-safety.md)

## Tests

```
Python:     249 tests
TypeScript: 233 tests
Total:      482 tests passing
Regressions across 5 weeks of dev: 0
```

## Live benchmarks (real Anthropic Haiku, real Modal sandboxes)

| # | Demo | Headline |
|---|---|---|
| 1 | Instagram-clone backend (4 engineers) | 3 stale-base overwrites caught |
| 2 | Data analysis pipeline (3 agents, disjoint files) | 2 BELIEF divergences caught (semantic conflicts scope-overlap can't see) |
| 3 | Auto-merge demo (3 engineers + same file) | 3/3 fields preserved (vs 2/3 baseline) |
| 4 | Cross-framework test (LangGraph + CrewAI on one session) | 3 conflicts including 2 cross-framework |
| 5 | **SDLC benchmark — multi-tenant SaaS billing platform (6 agents, 4 stages)** | **Coherence 0.33 → 0.93** (2.8x improvement) |
| 6 | **Autonomous observer test (LangGraph orchestrator + 4 workers)** | **0 conflicts caught** — orchestrator pre-deconflicted. Honest finding that narrowed the pitch. |

Full numbers + capture artifacts: [`bench/benchmarks.md`](bench/benchmarks.md) and [`bench/results/`](bench/results/).

## Self-hosted by design

Synapse never makes a paid LLM call without your explicit `set_llm()` config. There is no Synapse SaaS. Run it on your own infrastructure with `synapse up`.

## License

Apache 2.0 — see [`LICENSE`](LICENSE).

## Contributing

Issues + PRs welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md). The protocol spec changes go through [`spec/adr/`](spec/adr/) — open an ADR before proposing breaking changes.

---

Built by Aadit Rajgor · v0.2.1-alpha · 2026
