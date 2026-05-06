# Graph Report - synapse  (2026-05-06)

## Corpus Check
- 50 files · ~20,526 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 523 nodes · 848 edges · 41 communities (22 shown, 19 thin omitted)
- Extraction: 67% EXTRACTED · 33% INFERRED · 0% AMBIGUOUS · INFERRED: 283 edges (avg confidence: 0.66)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `16735c1d`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 40|Community 40]]

## God Nodes (most connected - your core abstractions)
1. `Agent` - 28 edges
2. `Coordinator` - 23 edges
3. `Bus` - 23 edges
4. `GeminiAdapter` - 23 edges
5. `BackendCapabilities` - 22 edges
6. `AnthropicAdapter` - 22 edges
7. `BackendUnavailable` - 21 edges
8. `StateGraph` - 20 edges
9. `Router` - 19 edges
10. `MockAdapter` - 19 edges

## Surprising Connections (you probably didn't know these)
- `make_coordinator_backend()` --calls--> `GeminiAdapter`  [INFERRED]
  examples/coordinator_demo.py → sdk-python/synapse/adapters/hosted/gemini_adapter.py
- `main()` --calls--> `Bus`  [INFERRED]
  examples/coordinator_demo.py → sdk-python/synapse/bus.py
- `main()` --calls--> `Agent`  [INFERRED]
  examples/coordinator_demo.py → sdk-python/synapse/agent.py
- `main()` --calls--> `MockAdapter`  [INFERRED]
  examples/coordinator_demo.py → sdk-python/synapse/adapters/mock.py
- `main()` --calls--> `Coordinator`  [INFERRED]
  examples/coordinator_demo.py → runtime/coordinator/agent.py

## Communities (41 total, 19 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.08
Nodes (36): BaseModel, Enum, Agent, lifecycle(), Synapse Agent — the developer-facing surface.  Phase 1 surface area: register, e, Emit an INTENTION and (if blocking) wait briefly for CONFLICT/BLOCK signals., Emit an INTENTION and (if blocking) wait briefly for CONFLICT/BLOCK signals., Drain inbox during the gate window, return any CONFLICT/BLOCK targeting this int (+28 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (27): BackendUnavailable, InferenceAdapter, InferenceAdapter Protocol — see spec/adapter.md for the canonical contract., Opaque handle to an in-flight generation. Adapter-specific contents., Raised when the backend cannot be reached. SDK falls back to no-coordination mod, Raised when an operation is requested that the backend does not support     (e.g, StreamHandle, UnsupportedCapability (+19 more)

### Community 2 - "Community 2"
Cohesion: 0.07
Nodes (21): conflicts(), find_overlapping_scopes(), has_write(), _intersect_parts(), parse_scope(), patterns_intersect(), pool(), Postgres state graph client.  Provides agent registration, intention claim/relea (+13 more)

### Community 3 - "Community 3"
Cohesion: 0.07
Nodes (21): collect(), main(), make_backend(), Phase 2 deliverable — same conflict demo, real LLM (Gemini by default).  Drop-in, Pick a hosted adapter based on env. Cheap defaults.      Gemini auto-uses Vertex, Read up to N tokens from a streaming handle and return the joined text., _section(), _wait_for_ready() (+13 more)

### Community 4 - "Community 4"
Cohesion: 0.08
Nodes (20): main(), make_coordinator_backend(), Phase 4 deliverable — coordinator agent in action.  Three scenarios: 1. **Belief, Coordinator uses Gemini Flash (free via Vertex AI)., _section(), _wait_for_ready(), main(), make_gemini() (+12 more)

### Community 5 - "Community 5"
Cohesion: 0.13
Nodes (14): AgentBelief, BeliefDivergence, beliefs_from_db_rows(), detect_divergences(), Belief divergence detection.  When multiple agents assert different values for t, Two or more agents holding distinct values for the same key., Structural equality, with float fuzz., Group beliefs by key. Within each key, find sets of agents with     distinct val (+6 more)

### Community 6 - "Community 6"
Cohesion: 0.11
Nodes (13): agent_inbox(), Bus, Redis Streams client for the Synapse message bus.  Conventions: - Session-wide s, Single-consumer inbox reader. Caller tracks last_id., Non-blocking: read all available inbox messages since last_id and return them., Async Redis Streams wrapper with envelope serialization., Publish to the session-wide stream. Returns the Redis stream entry ID., Publish directly to a specific agent's inbox. (+5 more)

### Community 7 - "Community 7"
Cohesion: 0.12
Nodes (14): Token, main(), Phase 1 deliverable — two-agent conflict demo.  Demonstrates Synapse's core valu, Generic wait-for-ready: retries `connect_fn()` until it succeeds or retries exha, _section(), _wait_for_postgres_ready(), _wait_for_ready(), Modal serverless GPU engine for Synapse native-tier adapter.  Phase 3 ships with (+6 more)

### Community 8 - "Community 8"
Cohesion: 0.09
Nodes (23): Architecture at a glance, Author, code:block1 (┌─────────────────────────────────────────────────┐), code:bash (# Bring up Redis + Postgres + initial schema), code:bash (pytest sdk-python/tests/), code:block4 (synapse/), Contributing, Design principles (+15 more)

### Community 9 - "Community 9"
Cohesion: 0.1
Nodes (19): code:block1 (scope        := segment ("." segment)* [":" modifier]), code:block2 (Agent A: scope=["auth.middleware:w"]), code:block3 (Agent A: scope=["db.users.schema:r"]), code:block4 (Agent A: scope=["db.users.schema:r"]), code:block5 (Agent A: scope=["db.users.**:w"]), code:block6 (Agent A: scope=["auth.middleware:w"], blocks_others=["auth.*), Conflict Semantics, Dependency vs Conflict (+11 more)

### Community 10 - "Community 10"
Cohesion: 0.12
Nodes (16): code:bash (# Bring up Redis + Postgres with the initial schema applied), code:bash (docker compose ps), code:bash (python examples/two_agents_conflict_demo.py), code:block4 (============================================================), code:bash (docker compose down -v   # removes volumes (Postgres + Redis), code:bash (pip install pytest pytest-asyncio), examples, Expected output (+8 more)

### Community 11 - "Community 11"
Cohesion: 0.19
Nodes (10): MockAdapter, MockStreamState, Mock inference adapter — for Phase 1 demos and tests.  Doesn't talk to any LLM., Simulates a streaming LLM. Configurable scripted response per request.      Capa, _collect(), Tests for the mock inference adapter — the Phase 1 reference adapter., test_basic_streaming(), test_cancel_returns_partial() (+2 more)

### Community 12 - "Community 12"
Cohesion: 0.23
Nodes (5): cli(), Coordinator, main(), Synapse Coordinator — event-driven LLM-mediated session-wide reasoner.  Subscrib, Long-running coordinator process. Single instance per session.

### Community 13 - "Community 13"
Cohesion: 0.15
Nodes (14): code:bash (pip install -e .             # from this directory), code:python (import asyncio), code:bash (pip install pytest pytest-asyncio), code:block4 (synapse/), Install, Module layout, Module layout (planned), Phase 1 surface (+6 more)

### Community 14 - "Community 14"
Cohesion: 0.13
Nodes (14): Capability Flags, code:python (from typing import Protocol, AsyncIterator), Cost Reporting, Failure Modes, Implementing a New Adapter, InferenceAdapter Contract, Interface, `multi_tenant_isolation` (+6 more)

### Community 15 - "Community 15"
Cohesion: 0.15
Nodes (12): "But isn't this just X?", Co-existence Recipes, code:block1 (┌───────────────────────────────────────────────────────────), Direct Comparison, Positioning — Synapse vs MCP, A2A, LangGraph, AutoGen, Synapse + A2A, Synapse + LangGraph, Synapse + MCP (+4 more)

### Community 16 - "Community 16"
Cohesion: 0.2
Nodes (9): Action Items, ADR-0001: v1.0 Architecture Baseline, Components, Consequences, Context, Decision, Key Mechanisms, Resolved Open Questions (+1 more)

### Community 17 - "Community 17"
Cohesion: 0.22
Nodes (8): code:block1 (spec/), Layout, Reading Order, Synapse Protocol Specification, The Eight Message Types, The Seven Message Types, Validation, Versioning

### Community 18 - "Community 18"
Cohesion: 0.25
Nodes (7): Before opening a PR, code:bash (# Bring up Redis + Postgres), Contributing to Synapse, How to propose a new message type, License, Local development, Repository conventions

## Knowledge Gaps
- **174 isolated node(s):** `Phase 4 deliverable — coordinator agent in action.  Three scenarios: 1. **Belief`, `Coordinator uses Gemini Flash (free via Vertex AI).`, `Phase 3 deliverable — three agents, three backend tiers, one protocol.  Demonstr`, `Phase 1 deliverable — two-agent conflict demo.  Demonstrates Synapse's core valu`, `Phase 2 deliverable — same conflict demo, real LLM (Gemini by default).  Drop-in` (+169 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **19 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `StateGraph` connect `Community 4` to `Community 0`, `Community 2`, `Community 3`, `Community 7`, `Community 12`?**
  _High betweenness centrality (0.117) - this node is a cross-community bridge._
- **Why does `Coordinator` connect `Community 12` to `Community 0`, `Community 1`, `Community 4`, `Community 5`, `Community 6`?**
  _High betweenness centrality (0.107) - this node is a cross-community bridge._
- **Why does `Agent` connect `Community 0` to `Community 1`, `Community 3`, `Community 4`, `Community 6`, `Community 7`?**
  _High betweenness centrality (0.066) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `Agent` (e.g. with `InferenceAdapter` and `Bus`) actually correct?**
  _`Agent` has 16 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `Coordinator` (e.g. with `InferenceAdapter` and `Bus`) actually correct?**
  _`Coordinator` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `Bus` (e.g. with `Coordinator` and `Router`) actually correct?**
  _`Bus` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `GeminiAdapter` (e.g. with `BackendUnavailable` and `InferenceAdapter`) actually correct?**
  _`GeminiAdapter` has 15 INFERRED edges - model-reasoned connections that need verification._