# Graph Report - synapse  (2026-05-06)

## Corpus Check
- 101 files · ~45,145 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 914 nodes · 1540 edges · 81 communities (54 shown, 27 thin omitted)
- Extraction: 69% EXTRACTED · 31% INFERRED · 0% AMBIGUOUS · INFERRED: 483 edges (avg confidence: 0.66)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `82bb53f3`
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
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 79|Community 79]]
- [[_COMMUNITY_Community 80|Community 80]]

## God Nodes (most connected - your core abstractions)
1. `StateGraph` - 38 edges
2. `Bus` - 37 edges
3. `MockAdapter` - 35 edges
4. `Agent` - 32 edges
5. `Router` - 30 edges
6. `BackendUnavailable` - 29 edges
7. `Coordinator` - 28 edges
8. `InferenceAdapter` - 28 edges
9. `AnthropicAdapter` - 28 edges
10. `BackendCapabilities` - 27 edges

## Surprising Connections (you probably didn't know these)
- `main()` --calls--> `AnthropicAdapter`  [INFERRED]
  examples/anthropic_smoke.py → sdk-python/synapse/adapters/hosted/anthropic_adapter.py
- `make_coordinator_backend()` --calls--> `GeminiAdapter`  [INFERRED]
  examples/coordinator_demo.py → sdk-python/synapse/adapters/hosted/gemini_adapter.py
- `main()` --calls--> `StateGraph`  [INFERRED]
  examples/coordinator_demo.py → sdk-python/synapse/state.py
- `main()` --calls--> `Router`  [INFERRED]
  examples/coordinator_demo.py → runtime/router/worker.py
- `main()` --calls--> `Coordinator`  [INFERRED]
  examples/coordinator_demo.py → runtime/coordinator/agent.py

## Communities (81 total, 27 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (51): BaseModel, Enum, _finish(), main(), _main_with_timeout(), _make_a_backend(), _make_b_backend(), End-to-end test: full protocol flow with mid-stream inject driven by a real CONF (+43 more)

### Community 1 - "Community 1"
Cohesion: 0.05
Nodes (27): main(), Anthropic adapter live smoke test.  Verifies, against the real Anthropic API: 1., collect(), main(), make_backend(), Phase 2 deliverable — same conflict demo, real LLM (Gemini by default).  Drop-in, Pick a hosted adapter based on env. Cheap defaults.      Gemini auto-uses Vertex, Read up to N tokens from a streaming handle and return the joined text. (+19 more)

### Community 2 - "Community 2"
Cohesion: 0.07
Nodes (21): conflicts(), find_overlapping_scopes(), has_write(), _intersect_parts(), parse_scope(), patterns_intersect(), pool(), Postgres state graph client.  Provides agent registration, intention claim/relea (+13 more)

### Community 3 - "Community 3"
Cohesion: 0.1
Nodes (30): FakeAnthropicEvent, FakeAnthropicInputJsonDelta, FakeAnthropicMessages, FakeAnthropicStream, FakeAnthropicStreamCtx, FakeAnthropicTextDelta, FakeAnthropicThinkingDelta, FakeOpenAIChoice (+22 more)

### Community 4 - "Community 4"
Cohesion: 0.09
Nodes (15): main(), Phase 5 deliverable — L3 semantic router in action.  L3 picks up messages that L, _section(), _wait_for_ready(), L3SemanticRouter, L3Stats, L3 semantic router — uses an LLM to decide cross-domain relevance for messages t, L3 only operates on THOUGHT and BELIEF messages; INTENTION/CONFLICT         alre (+7 more)

### Community 5 - "Community 5"
Cohesion: 0.1
Nodes (9): Raised when an operation tries to act on a request_id that belongs to a     diff, TenantViolation, Agent, agentInbox(), Bus, sessionStream(), isUlid(), makeEnvelope() (+1 more)

### Community 6 - "Community 6"
Cohesion: 0.11
Nodes (17): MockAdapter, Mock inference adapter — for Phase 1 demos and tests.  Doesn't talk to any LLM., Simulates a streaming LLM. Configurable scripted response per request.      Capa, Simulates a streaming LLM. Configurable scripted response per request.      Capa, main(), Phase 1 deliverable — two-agent conflict demo.  Demonstrates Synapse's core valu, Generic wait-for-ready: retries `connect_fn()` until it succeeds or retries exha, _section() (+9 more)

### Community 7 - "Community 7"
Cohesion: 0.09
Nodes (18): main(), make_gemini(), make_mock(), make_vllm_modal(), Phase 3 deliverable — three agents, three backend tiers, one protocol.  Demonstr, _section(), _wait_for_ready(), Agent (+10 more)

### Community 8 - "Community 8"
Cohesion: 0.13
Nodes (14): AgentBelief, BeliefDivergence, beliefs_from_db_rows(), detect_divergences(), Belief divergence detection.  When multiple agents assert different values for t, Two or more agents holding distinct values for the same key., Structural equality, with float fuzz., Group beliefs by key. Within each key, find sets of agents with     distinct val (+6 more)

### Community 9 - "Community 9"
Cohesion: 0.1
Nodes (9): Identifies who owns a request in a multi-tenant deployment.      All four fields, TenantContext, Shared multi-tenant isolation helpers for adapters.  Native and Local-API adapte, Mix into an adapter that advertises multi_tenant_isolation='request_id'.      Ad, RequestIdIsolatedMixin, Multi-tenant `request_id` isolation tests.  Validates that adapters with `multi_, Backward compatibility: pre-multi-tenant code passes no tenant.         Default, TestMockAdapterTenantIsolation (+1 more)

### Community 10 - "Community 10"
Cohesion: 0.11
Nodes (12): agent_inbox(), Bus, Redis Streams client for the Synapse message bus.  Conventions: - Session-wide s, Single-consumer inbox reader. Caller tracks last_id., Non-blocking: read all available inbox messages since last_id and return them., Async Redis Streams wrapper with envelope serialization., Publish to the session-wide stream. Returns the Redis stream entry ID., Publish directly to a specific agent's inbox. (+4 more)

### Community 11 - "Community 11"
Cohesion: 0.09
Nodes (23): Architecture at a glance, Author, code:block1 (┌─────────────────────────────────────────────────┐), code:bash (# Bring up Redis + Postgres + initial schema), code:bash (pytest sdk-python/tests/), code:block4 (synapse/), Contributing, Design principles (+15 more)

### Community 12 - "Community 12"
Cohesion: 0.13
Nodes (18): GatewayState, get_agents(), get_beliefs(), get_intentions(), get_recent_events(), lifespan(), list_sessions(), _parse_jsonb() (+10 more)

### Community 13 - "Community 13"
Cohesion: 0.13
Nodes (16): _build_backend(), _percentile(), `synapse bench` — standardized backend benchmark.  Workloads: - pair-coding:, run_bench(), _wait_ready(), cmd_bench(), cmd_spec_validate(), `synapse` CLI entry point.  Subcommands: - `synapse spec validate [PATH ...]` — (+8 more)

### Community 14 - "Community 14"
Cohesion: 0.1
Nodes (19): code:block1 (scope        := segment ("." segment)* [":" modifier]), code:block2 (Agent A: scope=["auth.middleware:w"]), code:block3 (Agent A: scope=["db.users.schema:r"]), code:block4 (Agent A: scope=["db.users.schema:r"]), code:block5 (Agent A: scope=["db.users.**:w"]), code:block6 (Agent A: scope=["auth.middleware:w"], blocks_others=["auth.*), Conflict Semantics, Dependency vs Conflict (+11 more)

### Community 16 - "Community 16"
Cohesion: 0.2
Nodes (12): AgentRole, AgentRun, Product, ProductRun, cli(), main(), Router worker.  Consumes a session stream via consumer group 'router'. For each, Glob-style topic matching (auth.* matches auth.middleware). (+4 more)

### Community 17 - "Community 17"
Cohesion: 0.15
Nodes (7): main(), OpenAI adapter live smoke test.  Verifies, against the real OpenAI API: 1. Can i, OpenAIAdapter, OpenAI hosted adapter.  Same cached-restart injection pattern as Anthropic. Open, Hosted-tier adapter for OpenAI., adapter(), TestOpenAIAdapter

### Community 18 - "Community 18"
Cohesion: 0.12
Nodes (16): code:bash (# Bring up Redis + Postgres with the initial schema applied), code:bash (docker compose ps), code:bash (python examples/two_agents_conflict_demo.py), code:block4 (============================================================), code:bash (docker compose down -v   # removes volumes (Postgres + Redis), code:bash (pip install pytest pytest-asyncio), examples, Expected output (+8 more)

### Community 19 - "Community 19"
Cohesion: 0.23
Nodes (5): cli(), Coordinator, main(), Synapse Coordinator — event-driven LLM-mediated session-wide reasoner.  Subscrib, Long-running coordinator process. Single instance per session.

### Community 20 - "Community 20"
Cohesion: 0.15
Nodes (10): InferenceAdapter, InferenceAdapter Protocol — see spec/adapter.md for the canonical contract., Raised when an operation is requested that the backend does not support     (e.g, Opaque handle to an in-flight generation. Adapter-specific contents., Raised when an operation is requested that the backend does not support     (e.g, StreamHandle, UnsupportedCapability, MockStreamState (+2 more)

### Community 21 - "Community 21"
Cohesion: 0.15
Nodes (14): code:bash (pip install -e .             # from this directory), code:python (import asyncio), code:bash (pip install pytest pytest-asyncio), code:block4 (synapse/), Install, Module layout, Module layout (planned), Phase 1 surface (+6 more)

### Community 22 - "Community 22"
Cohesion: 0.13
Nodes (14): Capability Flags, code:python (from typing import Protocol, AsyncIterator), Cost Reporting, Failure Modes, Implementing a New Adapter, InferenceAdapter Contract, Interface, `multi_tenant_isolation` (+6 more)

### Community 23 - "Community 23"
Cohesion: 0.14
Nodes (5): Tests for Phase 3 adapters — Ollama (local-API) and vLLM-via-Modal (native).  Al, Each tier should have characteristic overhead and isolation defaults., TestOllamaAdapter, TestPhaseThreeAdaptersImportable, TestVLLMModalAdapter

### Community 24 - "Community 24"
Cohesion: 0.29
Nodes (12): _extract_url_field_name(), main(), _make_backend(), _print_table(), Multi-agent product development simulation — runs the SAME product-build scenari, Run one agent without any coordination — pure LLM call., Heuristically pull which field name was used. Recognizes URL-shortener     field, _run_agent_independent() (+4 more)

### Community 25 - "Community 25"
Cohesion: 0.15
Nodes (12): "But isn't this just X?", Co-existence Recipes, code:block1 (┌───────────────────────────────────────────────────────────), Direct Comparison, Positioning — Synapse vs MCP, A2A, LangGraph, AutoGen, Synapse + A2A, Synapse + LangGraph, Synapse + MCP (+4 more)

### Community 26 - "Community 26"
Cohesion: 0.3
Nodes (11): _llm_judge(), main(), make_backend(), _print_summary(), Realistic mid-stream injection test — proves the model BEHAVIOR changes, not jus, Use the same backend as a judge. Strict JSON request., _read_to_completion(), _read_until_chars() (+3 more)

### Community 27 - "Community 27"
Cohesion: 0.17
Nodes (11): code:bash (npm install @synapse-protocol/sdk), code:ts (import { Agent, Bus, MockAdapter } from "@synapse-protocol/s), code:ts (const owner = { tenant_id: "acme", agent_id: "a1", session_i), code:bash (npm install), Install, Multi-tenant isolation, Quickstart, Roadmap (+3 more)

### Community 28 - "Community 28"
Cohesion: 0.18
Nodes (3): main(), LangGraph-style product-dev demo using @synapse_node decorator.  Demonstrates ho, StateGraph

### Community 29 - "Community 29"
Cohesion: 0.27
Nodes (5): _messages_to_prompt(), vLLM-via-Modal native adapter.  Talks to a Modal-deployed vLLM engine over Modal, Connects to a deployed Modal vLLM engine via RPC.      Args:         modal_app:, Lazy-resolve the deployed Modal class. Caches across calls., VLLMModalAdapter

### Community 30 - "Community 30"
Cohesion: 0.24
Nodes (6): _messages_to_prompt(), OllamaAdapter, Ollama local-API adapter.  Talks to a locally-running Ollama server (default htt, Local-API resume: cancel stream, restart with last context tokens.          If t, Local-API tier adapter for Ollama.      Args:         model: Ollama model tag (e, Verify Ollama is reachable and the model is available.

### Community 31 - "Community 31"
Cohesion: 0.18
Nodes (10): Action Items, ADR-0002: Protocol v1.0 Freeze, Backward-compatible (allowed in 1.x), Backward-incompatible (requires 2.0), Consequences, Context, Decision, Evolution Rules (+2 more)

### Community 32 - "Community 32"
Cohesion: 0.22
Nodes (5): Modal serverless GPU engine for Synapse native-tier adapter.  Uses real **vLLM**, Stateful container hosting a real vLLM AsyncLLMEngine.      Each container insta, Stateful container hosting a transformers-based engine.      Named `VLLMEngine`, smoke_test(), VLLMEngine

### Community 33 - "Community 33"
Cohesion: 0.31
Nodes (5): BackendUnavailable, Raised when the backend cannot be reached. SDK falls back to no-coordination mod, Raised when the backend cannot be reached. SDK falls back to no-coordination mod, Two auth modes:         - **API key**: pass api_key=... or set GOOGLE_API_KEY/GE, BackendCapabilities

### Community 34 - "Community 34"
Cohesion: 0.38
Nodes (4): Token, RuntimeError, str, make()

### Community 35 - "Community 35"
Cohesion: 0.2
Nodes (9): bench, code:bash (synapse bench --backend mock --workload conflict-heavy), Pending backends, Recorded results, Recorded results (this session), Run, Synapse Benchmark Results, What the report contains (+1 more)

### Community 36 - "Community 36"
Cohesion: 0.2
Nodes (9): Action Items, ADR-0001: v1.0 Architecture Baseline, Components, Consequences, Context, Decision, Key Mechanisms, Resolved Open Questions (+1 more)

### Community 37 - "Community 37"
Cohesion: 0.2
Nodes (9): Architecture, code:bash (# 1. Bring up infrastructure (from repo root)), code:bash (python examples/two_agents_conflict_demo.py), code:block3 (Browser (Next.js, :3000)), Layout, Production deploy notes (later), Run it, Synapse Observability UI (+1 more)

### Community 38 - "Community 38"
Cohesion: 0.25
Nodes (7): Exception, _ensure_agent(), _ensure_connections(), LangGraph integration — wrap any node so it participates in Synapse coordination, Raised by a synapse_node when a CONFLICT arrives during the gate window.      Th, Idempotently connect Bus + StateGraph. Returns the shared instances., SynapseConflict

### Community 39 - "Community 39"
Cohesion: 0.22
Nodes (8): code:bash (pip install -e sdk-python), Endpoints, Environment, Implementation notes, REST, Run, Synapse Observability Gateway, WebSocket

### Community 40 - "Community 40"
Cohesion: 0.22
Nodes (8): code:block1 (spec/), Layout, Reading Order, Synapse Protocol Specification, The Eight Message Types, The Seven Message Types, Validation, Versioning

### Community 41 - "Community 41"
Cohesion: 0.25
Nodes (7): Before opening a PR, code:bash (# Bring up Redis + Postgres), Contributing to Synapse, How to propose a new message type, License, Local development, Repository conventions

### Community 42 - "Community 42"
Cohesion: 0.43
Nodes (6): main(), make_coordinator_backend(), Phase 4 deliverable — coordinator agent in action.  Three scenarios: 1. **Belief, Coordinator uses Gemini Flash (free via Vertex AI)., _section(), _wait_for_ready()

### Community 43 - "Community 43"
Cohesion: 0.43
Nodes (3): FakeCrewTask, main(), CrewAI-style product-dev demo using synapse_task integration.  This example show

## Knowledge Gaps
- **275 isolated node(s):** `Anthropic adapter live smoke test.  Verifies, against the real Anthropic API: 1.`, `Phase 4 deliverable — coordinator agent in action.  Three scenarios: 1. **Belief`, `Coordinator uses Gemini Flash (free via Vertex AI).`, `CrewAI-style product-dev demo using synapse_task integration.  This example show`, `End-to-end test: full protocol flow with mid-stream inject driven by a real CONF` (+270 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **27 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `InferenceAdapter` connect `Community 20` to `Community 0`, `Community 33`, `Community 1`, `Community 4`, `Community 5`, `Community 6`, `Community 7`, `Community 38`, `Community 16`, `Community 17`, `Community 19`, `Community 26`, `Community 29`, `Community 30`?**
  _High betweenness centrality (0.110) - this node is a cross-community bridge._
- **Why does `StateGraph` connect `Community 28` to `Community 0`, `Community 1`, `Community 2`, `Community 4`, `Community 38`, `Community 7`, `Community 6`, `Community 42`, `Community 43`, `Community 12`, `Community 13`, `Community 16`, `Community 19`, `Community 24`?**
  _High betweenness centrality (0.107) - this node is a cross-community bridge._
- **Why does `AnthropicAdapter` connect `Community 1` to `Community 0`, `Community 33`, `Community 34`, `Community 13`, `Community 17`, `Community 19`, `Community 20`, `Community 24`, `Community 26`?**
  _High betweenness centrality (0.076) - this node is a cross-community bridge._
- **Are the 29 inferred relationships involving `StateGraph` (e.g. with `FakeCrewTask` and `TestResult`) actually correct?**
  _`StateGraph` has 29 INFERRED edges - model-reasoned connections that need verification._
- **Are the 24 inferred relationships involving `Bus` (e.g. with `FakeCrewTask` and `TestResult`) actually correct?**
  _`Bus` has 24 INFERRED edges - model-reasoned connections that need verification._
- **Are the 18 inferred relationships involving `MockAdapter` (e.g. with `RequestIdIsolatedMixin` and `InferenceAdapter`) actually correct?**
  _`MockAdapter` has 18 INFERRED edges - model-reasoned connections that need verification._
- **Are the 20 inferred relationships involving `Agent` (e.g. with `InferenceAdapter` and `Bus`) actually correct?**
  _`Agent` has 20 INFERRED edges - model-reasoned connections that need verification._