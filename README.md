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

**Pre-alpha — Phase 0 (spec lock) complete. Phase 1 (runnable demo) in progress.**

### What works today

- Protocol specification (`spec/protocol-v1.0/`): 8 JSON Schemas covering envelope, agent registration, and 8 message types (THOUGHT, INTENTION, PIVOT, BELIEF, BLOCK, CONFLICT, RESOLUTION, COST_REPORT)
- Inference Adapter contract (`spec/adapter.md`): three-tier abstraction (Native / Local-API / Hosted)
- Conflict semantics (`spec/conflict-semantics.md`): scope matching rules
- Postgres state graph schema (`runtime/migrations/0001_initial_schema.sql`)
- Docker Compose stack (Redis 7.4 + Postgres 16) — brings up infrastructure only

### What does not work yet

- Python SDK is a stub — implementation lands in Phase 1
- Router (L1/L2/L3) — Phase 1 (L1+L2), Phase 5 (L3)
- Coordinator agent — Phase 4
- Inference adapters (Anthropic, vLLM, Ollama, OpenAI, Gemini) — Phases 2-5
- Observability UI — Phase 6
- Benchmark CLI — Phase 6

### Roadmap

| Phase | Scope | Target |
|---|---|---|
| 0 — Spec lock | Protocol schemas, adapter contract, ADRs | **Complete** |
| 1 — Runnable demo | SDK skeleton, bus, state graph, L1/L2 router, mocked backend, two-agent conflict demo | In progress |
| 2 — Real backend | Anthropic hosted adapter + append-and-continue | Weeks 3-4 |
| 3 — Multi-backend | vLLM (native) + Ollama (local-API) adapters | Weeks 5-6 |
| 4 — Coordinator | Sonnet-class LLM coordinator + cost telemetry + belief divergence | Weeks 7-8 |
| 5 — Smart router | L3 semantic relevance + OpenAI/Gemini adapters | Weeks 9-10 |
| 6 — Adoption surface | UI + LangGraph/CrewAI integrations + benchmark CLI | Weeks 11-12 |
| 7 — Public release | Docs, blog posts, Show HN | Week 13 |

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

## Quickstart (when Phase 1 ships)

```bash
# Bring up the infrastructure
docker compose up -d

# Run the conflict demo (Phase 1 deliverable)
python examples/two_agents_conflict_demo.py
```

When Phase 1 ships, you'll see two agents both claim `auth.middleware`, the router detect the overlap, and the second agent receive a `CONFLICT` signal and pivot — all without any human in the loop.

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
