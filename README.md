# Synapse

> A real-time coordination protocol for parallel AI agents working in the same session.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Status: Pre-alpha](https://img.shields.io/badge/Status-Pre--alpha-orange.svg)](#status)
[![Spec: v1.0](https://img.shields.io/badge/Spec-v1.0-green.svg)](spec/)

## What this is

Synapse is a coordination layer for multi-agent AI systems. When multiple agents work in parallel on the same project, repository, or task, Synapse lets them announce intentions before acting, detect conflicts before they become collisions, and pivot together when one agent's work changes the picture for the others.

Think of it as **OpenTelemetry + Redis Streams + a conflict-aware intent protocol** for autonomous agents — the layer that prevents three coding agents from racing each other to modify the same file with three different ideas.

## What this is *not*

| Synapse is | Synapse is not |
|---|---|
| Coordination *inside* one work session | A cross-vendor agent interop standard ([A2A](https://github.com/google/A2A) covers that) |
| Pre-action intent broadcasting | Tool/context provisioning ([MCP](https://modelcontextprotocol.io) covers that) |
| Middleware for any agent runtime | A new agent framework ([LangGraph](https://github.com/langchain-ai/langgraph), [CrewAI](https://github.com/crewAIInc/crewAI), [AutoGen](https://github.com/microsoft/autogen) cover that) |
| Conflict detection + observability | A replacement for any of the above |

See [`spec/positioning.md`](spec/positioning.md) for the full landscape.

## Status

**v0.1.0-alpha — feature-complete.** v0.2 in planning: re-position around audit + observability, BYO-LLM, framework-agnostic via OpenInference. See [`docs/roadmap/v0.2-observability-and-safety.md`](docs/roadmap/v0.2-observability-and-safety.md) and [`spec/adr/ADR-0003-byo-llm-and-audit-first.md`](spec/adr/ADR-0003-byo-llm-and-audit-first.md).

### What works today (v0.1)

- **Protocol** — 8 message types (THOUGHT, INTENTION, PIVOT, BELIEF, BLOCK, CONFLICT, RESOLUTION, COST_REPORT) with frozen v1.0 schemas (`spec/protocol-v1.0/`)
- **Python SDK** (`sdk-python/`) — bus, state graph, Agent class, 5 inference adapters (Mock, Anthropic, OpenAI, Gemini, Ollama) — 123 tests passing
- **TypeScript SDK** (`sdk-typescript/`) — full mirror of Python SDK — 20 tests passing
- **Router** — L1 (rules) + L2 (SQL conflict, GIN-indexed scope[]) + L3 (LLM-mediated semantic), with `stale_base_overwrite` detection for sequential same-resource overwrites
- **Coordinator** — event-driven, belief-divergence detection, BLOCK escalation
- **Gateway** — FastAPI WebSocket + REST, broadcasts session events
- **Observability UI** — Next.js dashboard with AgentGrid, IntentionsTable, BeliefPanel, EventStream, CostChart, ReplayScrubber
- **CLI** — `synapse spec validate`, `synapse bench`
- **Framework integrations**:
  - **Hermes Agent** (Python): `wrap_tool_call_for_synapse` with multi-agent registry
  - **Paperclip AI** (TypeScript): `wrapAdapterWithSynapse`
  - **OpenClaw** (TypeScript): `wrapExtensionWithSynapse` + `makeSynapseExtension`
  - **LangGraph**, **CrewAI**: `@synapse_node` / `synapse_task` decorators
- **Realistic product-dev tests** — 4-agent Instagram-clone backend + 4-agent data-analysis pipeline running real Anthropic Haiku 4.5 calls in Modal sandboxes (`runtime/modal/_payloads/real_app_*.py`)

### Where v0.2 is going

The honest distillation after pressure-testing v0.1 against five real multi-agent personas:

> **Synapse is the missing observability + safety layer for any multi-agent stack, with conflict detection as the headline safety feature.**
>
> Not a coordination protocol that happens to come with a dashboard.

v0.2 ships in 5 weeks of focused work:

| Week | Ship |
|---|---|
| 1 | `synapse audit` CLI — read-only conflict report on any framework's trace export (OpenInference / LangSmith / JSONL) |
| 2 | Universal `synapse.intend()` SDK + `synapse.set_llm()` (BYO-LLM) + LangGraph adapter |
| 3 | `synapse up` (one-line self-hosted) + dashboard re-positioning + CrewAI / AutoGen / OpenAI Assistants adapters |
| 4 | `MergePolicy.{redirect, wait, abort, auto_merge}` + `critical_scopes` selective enforcement |
| 5 | BELIEF divergence on integration path — catches semantic conflicts that scope-overlap detection misses |

See the [v0.2 roadmap](docs/roadmap/v0.2-observability-and-safety.md) for the full plan, demo gallery, and what we're explicitly *not* doing.

## What it does (when complete)

- **Intention broadcasting** — agents announce what they're about to do, with declared scope and expected outcome, before any tool call fires
- **Conflict detection** — overlapping scopes are detected at the bus layer; affected agents receive a `CONFLICT` signal before collision
- **Mid-stream injection** *(Phase 2+)* — high-urgency signals can interrupt active LLM generation via append-and-continue (true KV append on native backends, cached restart on hosted)
- **Backend-agnostic** — same SDK across vLLM, Ollama, Anthropic, OpenAI, Gemini via the typed Inference Adapter Layer
- **Live observability** *(Phase 6)* — see every agent's intentions, conflicts, and pivots in real-time

## Architecture at a glance

```
┌─────────────────────────────────────────────────┐
│             Synapse Core                        │
│  Bus (Redis) · State Graph (Postgres) ·         │
│  Router (L1/L2/L3) · Coordinator (LLM agent)    │
└─────────────────┬───────────────────────────────┘
                  │ inbox streams
                  ▼
       ┌─────────────────────────┐
       │      Synapse SDK        │
       │  Inference Adapter      │
       │  ┌───────┬───────┬────┐ │
       │  │Native │Local  │Host│ │
       │  └───────┴───────┴────┘ │
       └─────────────────────────┘
            │       │       │
        vLLM/etc Ollama  Claude/GPT
```

> The **Coordinator** is a model-agnostic role. The first reference implementation uses a Sonnet-class hosted model, but any sufficiently capable LLM can fill it.

See [`spec/`](spec/) for the protocol definitions, adapter contract, and conflict semantics. The full architecture and execution plan are in [`docs/Synapse_Architecture_and_Execution_Plan.docx`](docs/Synapse_Architecture_and_Execution_Plan.docx).

## Quickstart

Phase 1 has shipped — the conflict demo runs end-to-end with mocked inference.

```bash
# Bring up Redis + Postgres + initial schema
docker compose up -d

# Install the SDK
pip install -e sdk-python

# Run the conflict demo
python examples/two_agents_conflict_demo.py
```

You'll see two agents both claim `auth.middleware`, the router detect the overlap, the second agent receive a `CONFLICT` signal during its 500ms pre-execution gate, and pivot to `auth.logging` — all without any human in the loop.

See [`examples/README.md`](examples/README.md) for expected output and how it works.

### Run the unit tests (no Docker needed)

```bash
pytest sdk-python/tests/
```

39 tests covering scope matching, envelope construction, message models, and the mock adapter.

## Repository layout

```
synapse/
├── spec/                      Protocol specifications
│   ├── protocol-v1.0/         JSON Schemas for envelope + 8 message types
│   ├── adapter.md             InferenceAdapter interface contract
│   ├── conflict-semantics.md  Scope matching rules
│   ├── positioning.md         Synapse vs MCP / A2A / LangGraph / AutoGen
│   └── adr/                   Architectural Decision Records
├── sdk-python/                Python SDK (Phase 1+)
├── runtime/                   Bus + state graph + router + coordinator
├── adapters/
│   ├── native/                vLLM, SGLang, TGI, llama.cpp
│   ├── local/                 Ollama, LM Studio
│   └── hosted/                Anthropic, OpenAI, Gemini
├── ui/                        Observability UI (Next.js, Phase 6)
├── bench/                     synapse bench CLI (Phase 6)
├── examples/                  Demo scenarios
├── docs/                      Architecture and execution plan
└── docker-compose.yml         Local dev stack (Redis + Postgres)
```

## Design principles

1. **Fail-open.** Synapse going down must not block agent work — agents continue uncoordinated and reconcile when the bus recovers.
2. **Sub-50ms happy path.** Coordination overhead must be invisible in the no-conflict case.
3. **Protocol over framework.** The wire format outlives any single implementation.
4. **Backend-agnostic, capability-aware.** Same SDK across all inference backends; routing adapts to each backend's capabilities.
5. **Honest costs.** Every signal's token cost is reported and visible.
6. **Operational state, not raw reasoning.** Agents share intentions, scopes, beliefs, and pivots — not private chain-of-thought tokens.

## Contributing

The protocol is the artifact that matters most. Before sending a PR that changes message schemas, the adapter contract, or routing semantics, open an issue with an ADR-style proposal. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache 2.0 — see [LICENSE](LICENSE).

## Author

Aadit Rajgor ([@arajgor1](https://github.com/arajgor1))
