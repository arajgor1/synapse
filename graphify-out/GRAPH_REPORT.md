# Graph Report - synapse  (2026-05-06)

## Corpus Check
- 32 files · ~11,366 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 342 nodes · 504 edges · 28 communities (17 shown, 11 thin omitted)
- Extraction: 72% EXTRACTED · 28% INFERRED · 0% AMBIGUOUS · INFERRED: 140 edges (avg confidence: 0.63)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `b2fb370f`
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
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]

## God Nodes (most connected - your core abstractions)
1. `Agent` - 20 edges
2. `Bus` - 18 edges
3. `conflicts()` - 17 edges
4. `TestEnvelope` - 17 edges
5. `TestPayloadModels` - 17 edges
6. `Router` - 16 edges
7. `MockAdapter` - 16 edges
8. `StateGraph` - 15 edges
9. `TestAgentRegistration` - 15 edges
10. `Synapse` - 15 edges

## Surprising Connections (you probably didn't know these)
- `main()` --calls--> `Bus`  [INFERRED]
  examples/two_agents_conflict_demo.py → sdk-python/synapse/bus.py
- `main()` --calls--> `MockAdapter`  [INFERRED]
  examples/two_agents_conflict_demo.py → sdk-python/synapse/adapters/mock.py
- `main()` --calls--> `Agent`  [INFERRED]
  examples/two_agents_conflict_demo.py → sdk-python/synapse/agent.py
- `Router` --uses--> `Bus`  [INFERRED]
  runtime/router/worker.py → sdk-python/synapse/bus.py
- `Router` --uses--> `Conflict`  [INFERRED]
  runtime/router/worker.py → sdk-python/synapse/messages.py

## Communities (28 total, 11 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.07
Nodes (21): conflicts(), find_overlapping_scopes(), has_write(), _intersect_parts(), parse_scope(), patterns_intersect(), pool(), Postgres state graph client.  Provides agent registration, intention claim/relea (+13 more)

### Community 1 - "Community 1"
Cohesion: 0.13
Nodes (26): BaseModel, Enum, str, AgentRegistration, Belief, Block, Conflict, ConflictingIntention (+18 more)

### Community 2 - "Community 2"
Cohesion: 0.1
Nodes (22): BackendUnavailable, InferenceAdapter, InferenceAdapter Protocol — see spec/adapter.md for the canonical contract., Opaque handle to an in-flight generation. Adapter-specific contents., Raised when the backend cannot be reached. SDK falls back to no-coordination mod, Raised when an operation is requested that the backend does not support     (e.g, StreamHandle, Token (+14 more)

### Community 3 - "Community 3"
Cohesion: 0.11
Nodes (12): main(), Phase 1 deliverable — two-agent conflict demo.  Demonstrates Synapse's core valu, Smooth over docker-compose startup race., _section(), _wait_for_postgres_ready(), cli(), main(), Router worker.  Consumes a session stream via consumer group 'router'. For each (+4 more)

### Community 4 - "Community 4"
Cohesion: 0.11
Nodes (13): agent_inbox(), Bus, Redis Streams client for the Synapse message bus.  Conventions: - Session-wide s, Single-consumer inbox reader. Caller tracks last_id., Non-blocking: read all available inbox messages since last_id and return them., Async Redis Streams wrapper with envelope serialization., Publish to the session-wide stream. Returns the Redis stream entry ID., Publish directly to a specific agent's inbox. (+5 more)

### Community 5 - "Community 5"
Cohesion: 0.09
Nodes (23): Architecture at a glance, Author, code:block1 (┌─────────────────────────────────────────────────┐), code:bash (# Bring up Redis + Postgres + initial schema), code:bash (pytest sdk-python/tests/), code:block4 (synapse/), Contributing, Design principles (+15 more)

### Community 6 - "Community 6"
Cohesion: 0.1
Nodes (19): code:block1 (scope        := segment ("." segment)* [":" modifier]), code:block2 (Agent A: scope=["auth.middleware:w"]), code:block3 (Agent A: scope=["db.users.schema:r"]), code:block4 (Agent A: scope=["db.users.schema:r"]), code:block5 (Agent A: scope=["db.users.**:w"]), code:block6 (Agent A: scope=["auth.middleware:w"], blocks_others=["auth.*), Conflict Semantics, Dependency vs Conflict (+11 more)

### Community 7 - "Community 7"
Cohesion: 0.12
Nodes (16): code:bash (# Bring up Redis + Postgres with the initial schema applied), code:bash (docker compose ps), code:bash (python examples/two_agents_conflict_demo.py), code:block4 (============================================================), code:bash (docker compose down -v   # removes volumes (Postgres + Redis), code:bash (pip install pytest pytest-asyncio), examples, Expected output (+8 more)

### Community 8 - "Community 8"
Cohesion: 0.17
Nodes (6): Agent, lifecycle(), Synapse Agent — the developer-facing surface.  Phase 1 surface area: register, e, Emit an INTENTION and (if blocking) wait briefly for CONFLICT/BLOCK signals., Drain inbox during the gate window, return any CONFLICT/BLOCK targeting this int, Read all inbox messages since last drain. Returns envelopes (caller dispatches b

### Community 9 - "Community 9"
Cohesion: 0.15
Nodes (14): code:bash (pip install -e .             # from this directory), code:python (import asyncio), code:bash (pip install pytest pytest-asyncio), code:block4 (synapse/), Install, Module layout, Module layout (planned), Phase 1 surface (+6 more)

### Community 10 - "Community 10"
Cohesion: 0.13
Nodes (14): Capability Flags, code:python (from typing import Protocol, AsyncIterator), Cost Reporting, Failure Modes, Implementing a New Adapter, InferenceAdapter Contract, Interface, `multi_tenant_isolation` (+6 more)

### Community 11 - "Community 11"
Cohesion: 0.15
Nodes (12): "But isn't this just X?", Co-existence Recipes, code:block1 (┌───────────────────────────────────────────────────────────), Direct Comparison, Positioning — Synapse vs MCP, A2A, LangGraph, AutoGen, Synapse + A2A, Synapse + LangGraph, Synapse + MCP (+4 more)

### Community 12 - "Community 12"
Cohesion: 0.2
Nodes (9): Action Items, ADR-0001: v1.0 Architecture Baseline, Components, Consequences, Context, Decision, Key Mechanisms, Resolved Open Questions (+1 more)

### Community 13 - "Community 13"
Cohesion: 0.22
Nodes (8): code:block1 (spec/), Layout, Reading Order, Synapse Protocol Specification, The Eight Message Types, The Seven Message Types, Validation, Versioning

### Community 14 - "Community 14"
Cohesion: 0.25
Nodes (7): Before opening a PR, code:bash (# Bring up Redis + Postgres), Contributing to Synapse, How to propose a new message type, License, Local development, Repository conventions

## Knowledge Gaps
- **127 isolated node(s):** `Phase 1 deliverable — two-agent conflict demo.  Demonstrates Synapse's core valu`, `Smooth over docker-compose startup race.`, `Router worker.  Consumes a session stream via consumer group 'router'. For each`, `Glob-style topic matching (auth.* matches auth.middleware).`, `Synapse router — L1 (rules) + L2 (SQL conflict) for Phase 1.  L3 (semantic relev` (+122 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **11 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `StateGraph` connect `Community 3` to `Community 0`, `Community 8`, `Community 1`?**
  _High betweenness centrality (0.125) - this node is a cross-community bridge._
- **Why does `Agent` connect `Community 8` to `Community 1`, `Community 2`, `Community 3`, `Community 4`?**
  _High betweenness centrality (0.069) - this node is a cross-community bridge._
- **Why does `Bus` connect `Community 4` to `Community 8`, `Community 1`, `Community 3`?**
  _High betweenness centrality (0.067) - this node is a cross-community bridge._
- **Are the 11 inferred relationships involving `Agent` (e.g. with `InferenceAdapter` and `Bus`) actually correct?**
  _`Agent` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `Bus` (e.g. with `Router` and `Agent`) actually correct?**
  _`Bus` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `conflicts()` (e.g. with `.test_concurrent_reads_no_conflict()` and `.test_read_vs_write_conflicts()`) actually correct?**
  _`conflicts()` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `TestEnvelope` (e.g. with `AgentRegistration` and `BackendCapabilities`) actually correct?**
  _`TestEnvelope` has 12 INFERRED edges - model-reasoned connections that need verification._