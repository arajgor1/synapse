# Synapse

> **The safety layer for multi-agent AI on shared codebases.**
> Audit existing trace exports for silent collisions, prevent them live, resolve them with your own LLM.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Version: v0.2.2](https://img.shields.io/badge/Version-v0.2.2-blue.svg)](#status)
[![Spec: v1.0](https://img.shields.io/badge/Spec-v1.0-green.svg)](spec/protocol-v1.0/)
[![Tests](https://img.shields.io/badge/tests-324%20passing-brightgreen.svg)](#tests)
[![Adapters](https://img.shields.io/badge/adapters-12%20frameworks%20%2B%20OTel%20live-brightgreen.svg)](sdk-python/tests/test_adapter_health.py)
[![Latency](https://img.shields.io/badge/no--conflict%20latency-1.59ms%20median-brightgreen.svg)](bench/LATENCY.md)
[![AgenticFlict F1](https://img.shields.io/badge/AgenticFlict_F1-0.865-brightgreen.svg)](bench/results/agenticflict_benchmark.json)

---

## Try it in 60 seconds — no infra, no env vars

```bash
pip install synapse-protocol

# Terminal 1: live coordination dashboard, browser auto-opens
synapse watch --session demo

# Terminal 2: run any agent code in the same project tree
SYNAPSE_SESSION_ID=demo python your_agent_script.py
```

That's it. **No Redis, no Postgres, no env vars.** v0.2.2 ships zero-infra mode (in-memory bus + auto-SQLite at `~/.synapse/state.db` + auto-spawned in-process L2 router) so a fresh user sees real coordination value in two terminal commands.

The dashboard ticks live: every `synapse.intend()` call shows up; every cross-agent collision the in-process router catches surfaces with full attribution + scope info.

For multi-process coordination set `SYNAPSE_REDIS_URL` and `SYNAPSE_POSTGRES_DSN` and you get the live mode. Same code.

### Or: audit existing trace exports

```bash
pip install synapse-protocol
synapse audit ./traces.json
```

Supports OpenInference / OTel · LangSmith · AWS Bedrock Agents · GCP Vertex Agent Builder · Azure AI Agent Service · plain JSONL — auto-detected.

No trace? Try the [hosted audit tool](launch/hosted-audit/) (drag-drop a trace JSON in your browser, zero install).

### Catch a real collision in your own code (60-second demo)

```bash
git clone https://github.com/arajgor1/synapse
cd synapse/examples/crewai-marketing
python crew_no_synapse.py    # control: silently loses one writer's text
python crew.py               # with synapse: BOTH writers' work survives
```

`crew.py` runs three agents (Researcher → Writer → Editor) on a shared `drafts/` directory. Without Synapse, the Editor silently overwrites the Writer. With Synapse, the in-process router catches the file collision, the second writer's `IntentionHandle.has_conflicts` is True, and the demo pivots to a per-agent variant via `MergePolicy.work_on_different_scope`.

---

## Prior art and how Synapse differs

**Synapse is an open-source production-grade implementation in the *semantic-consensus* category recently formalized by Vivek Acharya** (["Semantic Consensus: Process-Aware Conflict Detection and Resolution for Enterprise Multi-Agent LLM Systems"](https://arxiv.org/abs/2604.16339), arXiv 2604.16339, March 2026).

We share the conflict taxonomy and SCF-aligned metrics:
- **Resource Contention** ↔ `scope_overlap`
- **Causal Violation** ↔ `stale_base_overwrite`
- **Contradictory Intent** ↔ BELIEF divergence path
- Plus the SCF resolution-tier hint (policy / capability / temporal) and the SAS drift score on every audit.

We differ in three ways:
1. **Audit-on-existing-trace-exports** with no middleware deployment, no agent-runtime patching, no hand-authored process model. SCF requires inline blocking; Synapse runs post-hoc on what your agents already emit.
2. **FS-watcher path for IDE/CLI agents** (Claude Code, Cursor, Codex CLI, Aider) that don't expose live coordination hooks.
3. **Real-world evidence on real published SDKs.** All 12 framework adapters confirmed patching the real published SDK at install time (see `tests/test_adapter_health.py`). 6 of those (autogen, langchain, langgraph, smolagents, crewai, agno) additionally verified through real LLM-driven dispatch with INTENTIONs persisted end-to-end in a Modal sandbox (see `bench/REAL_LIFE_TESTING.md` + `bench/results/v022_real_llm_e2e_*.json`). The other 4 (openai_agents, pydantic_ai, llama_index, google_adk) hit framework-specific internal-scheduler cross-loop bugs in their own code paths — install-only verified, follow-up fixes filed. SCF's evaluation uses simulated agents.

### Framework coverage (vs. Semantica's "Coming Soon" list)

| Framework | Synapse v0.2.2 | Semantica |
|---|---|---|
| **Agno** | ✅ shipped (FunctionCall.execute) | First-class (only one they ship) |
| **LangChain** | ✅ shipped (BaseTool.invoke/ainvoke) | "Coming soon" |
| **LangGraph** | ✅ shipped (callback) | "Coming soon" |
| **CrewAI** | ✅ shipped (Task.execute) | "Coming soon" |
| **LlamaIndex** | ✅ shipped (FunctionTool.call) | "Coming soon" |
| **AutoGen** | ✅ shipped (FunctionTool.run) | "Coming soon" |
| **OpenAI Agents** | ✅ shipped (function_tool) | "Coming soon" |
| **Google ADK** | ✅ shipped (BaseTool.run_async) | "Coming soon" |
| **Pydantic AI** | ✅ shipped (AbstractToolset.call_tool) | not on list |
| **smolagents** | ✅ shipped (Tool.__call__) | not on list |
| **Strands Agents (AWS)** | ✅ shipped (event_loop._handle_tool_execution) | not on list |
| **Hermes Agent** | ✅ shipped (sub-agent path) | not on list |

All 11 verified against the actual published packages by `tests/test_adapter_health.py`. Synapse ships all 7 of Semantica's "Coming Soon" list **today**, plus 4 more they don't list.

We also benchmark on the **AgenticFlict** dataset (Allamanis et al., arXiv 2604.03551 — 142,652 real AI-coding-agent PRs, 29,609 conflicting). On 5,408 paired PRs Synapse hits **F1 = 0.865, recall = 1.000, precision = 0.763** on the structural scope-overlap subtask. Per-agent: Claude Code F1 = 1.000, Cursor 0.970, Copilot 0.940, Devin 0.944, OpenAI Codex 0.786. Full results: [`bench/results/agenticflict_benchmark.json`](bench/results/agenticflict_benchmark.json).

---

## The empirical case (multi-orchestrator)

Two engineers, each running their own AI agent on the same repo, will silently overwrite each other and quietly disagree on the schema. **None of the alternatives catch it. Synapse does.**

Hold the agent behavior constant (real LangGraph multi-orchestrator run, May 8 2026). Vary the coordination strategy.

| Strategy | Silent file loss | Loud conflicts | Belief divergences caught |
|---|---|---|---|
| No coordination | **4 of 8 files** | 0 | 0 of 3 |
| Git branches + naive merge | 0 | 4 (loud) | **0 of 3** |
| PR + CI with pytest in loop | 3 | 1 | **1 of 3** (only schema-shaped) |
| Shared coordination.md | 2 | 0 | 0 of 3 |
| **Synapse `MergePolicy.auto_merge`** | **0** | **4 auto-merged** | **3 of 3** |

Source data + scoring oracle: [`bench/results/v02_pitch_phase1/`](bench/results/v02_pitch_phase1/RESULTS_REAL.md). Full 1-pager with caveats: [`docs/launch/PITCH_1PAGER.md`](docs/launch/PITCH_1PAGER.md). Honest IRL trust check on every claim: [`bench/TESTING_PROTOCOL.md`](bench/TESTING_PROTOCOL.md).

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
