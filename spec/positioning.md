# Positioning — Synapse vs MCP, A2A, LangGraph, AutoGen

> Multi-agent infrastructure has several emerging standards. Synapse does not compete with any of them. It slots underneath them. This doc explains where each layer fits.

## The Layered Picture

```
┌──────────────────────────────────────────────────────────────┐
│  Application: a multi-agent product (coding assistant,       │
│               research workflow, agentic SaaS, etc.)         │
└────────────────────────────────┬─────────────────────────────┘
                                 │
┌────────────────────────────────▼─────────────────────────────┐
│  Agent Framework Layer                                       │
│  LangGraph · CrewAI · AutoGen · custom orchestrators         │
│  → defines workflow shape, agent roles, handoffs             │
└────────────────────────────────┬─────────────────────────────┘
                                 │
┌────────────────────────────────▼─────────────────────────────┐
│  Cross-Vendor Interop (when agents from different orgs)      │
│  A2A (Agent2Agent Protocol)                                  │
│  → discovery, capability negotiation, cross-system messaging │
└────────────────────────────────┬─────────────────────────────┘
                                 │
┌────────────────────────────────▼─────────────────────────────┐
│  ★ Coordination Layer — Synapse ★                            │
│  → real-time intent broadcasting, conflict detection,        │
│    pivot signaling, observability inside one work session    │
└────────────────────────────────┬─────────────────────────────┘
                                 │
┌────────────────────────────────▼─────────────────────────────┐
│  Tool / Context Provisioning                                 │
│  MCP (Model Context Protocol)                                │
│  → connecting models to tools, files, databases, APIs        │
└────────────────────────────────┬─────────────────────────────┘
                                 │
┌────────────────────────────────▼─────────────────────────────┐
│  Inference                                                   │
│  Anthropic · OpenAI · Gemini · vLLM · Ollama · llama.cpp     │
└──────────────────────────────────────────────────────────────┘
```

## Direct Comparison

| Layer | What it solves | Synapse relationship |
|---|---|---|
| **MCP** | How a model connects to tools, files, APIs, external context | Synapse coordinates *before* an MCP tool call fires — checking whether the intended tool call conflicts with another agent's claim |
| **A2A** | How independent agents (often across vendors) discover and message each other | Synapse is the operational layer *inside* an A2A task — once two agents are talking via A2A, Synapse handles their fine-grained coordination |
| **LangGraph** | Build stateful agent workflows with conditional edges, supervisors, handoffs | Synapse is middleware — wraps LangGraph nodes so parallel branches coordinate without explicit edges |
| **AutoGen** | Multi-agent conversations and orchestration | Synapse adds pre-action conflict detection between AutoGen agents |
| **CrewAI** | Role-based agent teams with sequential or hierarchical processes | Synapse plugs into CrewAI tasks to surface cross-task conflicts |

## What Makes Synapse Distinct

The closest existing concept is **OpenTelemetry for distributed systems** — a vendor-neutral observability + signal layer that any framework can adopt. Synapse is that layer for autonomous agents, with three additions OpenTelemetry doesn't have:

1. **Pre-action signaling** — intentions are broadcast *before* tool calls, not after
2. **Built-in conflict detection** — scope overlaps generate routed signals, not just logs
3. **Bidirectional injection** — the runtime can inject signals back into agents, not just observe them

## Why This Matters for Adoption

Each layer in the stack has a different audience:

- **MCP** is adopted by developers building tool integrations
- **A2A** is adopted by platforms wanting cross-vendor agent interop
- **LangGraph / CrewAI / AutoGen** are adopted by developers building agentic apps
- **Synapse** is adopted by developers running multiple agents in parallel who hit coordination problems

These audiences overlap but are not identical. A team using LangGraph + MCP today does not need A2A (single-vendor), but absolutely benefits from Synapse the moment they parallelize work across two LangGraph nodes.

## "But isn't this just X?"

**"Isn't this just A2A?"**
No. A2A is about how Agent X (built by Org A) talks to Agent Y (built by Org B). Synapse is about how Agent X1, X2, X3 (all built by Org A, working on the same task) coordinate in real-time. A2A handles the wire-level interop; Synapse handles the operational semantics.

**"Isn't this just MCP?"**
No. MCP is agent ↔ resource (tools, data). Synapse is agent ↔ agent. They compose: an agent might use MCP to call a tool, with Synapse ensuring that tool call doesn't collide with another agent's claim.

**"Isn't this just LangGraph state?"**
LangGraph state is per-graph and synchronous — nodes read/write a shared state object. Synapse is async, distributed, and works across graph instances or framework boundaries. A LangGraph workflow can use both: state for the workflow's local logic, Synapse for cross-workflow coordination.

**"Isn't this just a message bus with steps?"**
Conceptually, yes. The protocol *is* a small set of message types over a bus. The contribution is the protocol design — eight purpose-built message types with conflict-detection semantics baked in — not the bus itself.

## Co-existence Recipes

### Synapse + MCP

Agent emits `INTENTION` declaring scope before invoking an MCP tool. Router checks for conflicts. If clear, agent proceeds; if conflicting, agent receives `CONFLICT` and pivots. Standard MCP tool call follows. MCP doesn't need to know Synapse exists.

### Synapse + LangGraph

Wrap each LangGraph node with the Synapse `@agent.intention` decorator. Parallel branches that touch shared state get conflict signals automatically. Sequential branches see no overhead.

### Synapse + A2A

Two organizations' agents discover and connect via A2A. Inside the resulting task, both agents register with a shared Synapse session and coordinate fine-grained actions through it. A2A handles the trust boundary; Synapse handles the operational tempo.

## Why Not Just Use a Database?

A database (or shared state object) gives you "what is currently true." It doesn't give you "what is *about* to happen." Synapse's contribution is the **prospective** layer — the part of multi-agent coordination that lives in the few hundred milliseconds between an agent deciding to act and the action actually firing. That window is invisible to any state-snapshot system.
