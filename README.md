# Synapse

> A coordination protocol for multi-agent AI systems — the connective tissue between thinking entities.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Status: Pre-alpha](https://img.shields.io/badge/Status-Pre--alpha-orange.svg)](#status)

## What is this?

Synapse is the missing layer for multi-agent AI systems. The agent runtime (turn-taking, tool use, retries) is solved by CrewAI, LangGraph, AutoGen, and the major SDKs. What does not exist is a **coordination protocol** that lets parallel agents share intentions, beliefs, and pivots in real-time so they can avoid conflicts, complement each other's work, and collaborate as a distributed mind rather than a pipeline.

Synapse is to multi-agent systems what HTTP is to web services: a small, opinionated protocol any framework can adopt as middleware.

## What it does

- **Real-time intention broadcasting** — agents announce what they're about to do, not just what they finished
- **Automatic conflict detection** — overlapping scopes are flagged before any tool call executes
- **Mid-stream signal injection** — high-urgency signals interrupt agents mid-generation via append-and-continue (no wasted work)
- **Backend-agnostic** — same SDK across vLLM, Ollama, Anthropic, OpenAI, Gemini via a typed Inference Adapter Layer
- **Live observability** — see every agent's thinking, intentions, and conflicts in real-time

## Architecture at a glance

```
┌─────────────────────────────────────────────────┐
│             Synapse Core                        │
│  Bus (Redis) · State Graph (Postgres) ·         │
│  Router (L1/L2/L3) · Coordinator (Sonnet)       │
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

See [`spec/`](spec/) for the protocol definitions and adapter contract. The full architecture and execution plan are in `Synapse_Architecture_and_Execution_Plan.docx` (sibling of this directory).

## Status

**Pre-alpha — protocol spec phase.** Phase 0 (decisions) is locked. Code begins Phase 1.

| Phase | Weeks | Status |
|---|---|---|
| 0 — Pre-code decisions, protocol freeze | This week | In progress |
| 1 — Skeleton + Hosted adapter (Anthropic) | 1-2 | Pending |
| 2 — Real coordination (L1/L2 router) | 3-4 | Pending |
| 3 — Mid-stream injection across all 3 tiers | 5-6 | Pending |
| 4 — Coordinator + cost telemetry | 7-8 | Pending |
| 5 — L3 semantic router | 9-10 | Pending |
| 6 — UI + adapters + benchmark tool | 11-12 | Pending |
| 7 — Public release | 13 | Pending |

## Quickstart (when implemented)

```bash
# Install
pip install synapse-protocol

# Start the runtime locally
docker compose up

# Register an agent
import synapse

agent = synapse.Agent(
    id="agent_a",
    session="my_session",
    backend=synapse.adapters.Anthropic(model="claude-sonnet-4.6"),
    subscribes=["auth.*"],
    scopes_owned=["auth.middleware"],
)

@agent.intention(scope=["auth.middleware"])
async def refactor_middleware():
    # SDK auto-emits INTENTION before, RESOLUTION after
    # Conflicts with other agents handled automatically
    ...
```

## Repository layout

```
synapse/
├── spec/                      Protocol specifications
│   ├── protocol-v1.0/         JSON Schemas for the 7 message types
│   └── adapter.md             InferenceAdapter interface contract
├── sdk-python/                Python SDK (Phase 1+)
├── runtime/                   Bus + state graph + router + coordinator
├── adapters/
│   ├── native/                vLLM, SGLang, TGI, llama.cpp
│   ├── local/                 Ollama, LM Studio
│   └── hosted/                Anthropic, OpenAI, Gemini
├── ui/                        Observability UI (Next.js)
├── bench/                     synapse bench CLI
├── examples/                  Demo scenarios
└── docker-compose.yml         Local dev stack (Redis + Postgres)
```

## Design principles

1. **Fail-open.** Synapse going down must not block agent work — agents continue uncoordinated and reconcile when the bus recovers.
2. **Sub-50ms happy path.** Coordination overhead must be invisible in the no-conflict case.
3. **Protocol over framework.** The wire format outlives any single implementation.
4. **Backend-agnostic, capability-aware.** Same SDK across all inference backends; routing adapts to each backend's capabilities.
5. **Honest costs.** Every signal's token cost is reported and visible.

## Contributing

The protocol is the artifact that matters most. Before sending a PR that changes message schemas, the adapter contract, or routing semantics, open an issue with an ADR-style proposal.

## License

Apache 2.0 — see [LICENSE](LICENSE).

## Author

Aadit Rajgor ([@arajgor1](https://github.com/arajgor1))
