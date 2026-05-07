# Graph Report - synapse  (2026-05-06)

## Corpus Check
- 96 files · ~38,865 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 862 nodes · 1396 edges · 72 communities (45 shown, 27 thin omitted)
- Extraction: 70% EXTRACTED · 30% INFERRED · 0% AMBIGUOUS · INFERRED: 417 edges (avg confidence: 0.66)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `51ee2e0a`
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
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]

## God Nodes (most connected - your core abstractions)
1. `MockAdapter` - 35 edges
2. `Agent` - 32 edges
3. `Bus` - 31 edges
4. `BackendUnavailable` - 29 edges
5. `StateGraph` - 28 edges
6. `BackendCapabilities` - 27 edges
7. `AnthropicAdapter` - 25 edges
8. `GeminiAdapter` - 25 edges
9. `Coordinator` - 23 edges
10. `TenantContext` - 23 edges

## Surprising Connections (you probably didn't know these)
- `main()` --calls--> `AnthropicAdapter`  [INFERRED]
  examples/anthropic_smoke.py → sdk-python/synapse/adapters/hosted/anthropic_adapter.py
- `make_coordinator_backend()` --calls--> `GeminiAdapter`  [INFERRED]
  examples/coordinator_demo.py → sdk-python/synapse/adapters/hosted/gemini_adapter.py
- `main()` --calls--> `Coordinator`  [INFERRED]
  examples/coordinator_demo.py → runtime/coordinator/agent.py
- `main()` --calls--> `Bus`  [INFERRED]
  examples/coordinator_demo.py → sdk-python/synapse/bus.py
- `main()` --calls--> `Agent`  [INFERRED]
  examples/coordinator_demo.py → sdk-python/synapse/agent.py

## Communities (72 total, 27 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (60): BaseModel, Enum, Exception, Wrap a CrewAI Task (or any callable) with Synapse coordination.      Returns a f, synapse_task(), _ensure_agent(), _ensure_connections(), LangGraph integration — wrap any node so it participates in Synapse coordination (+52 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (22): main(), Phase 5 deliverable — L3 semantic router in action.  L3 picks up messages that L, _section(), _wait_for_ready(), main(), OpenAI adapter live smoke test.  Verifies, against the real OpenAI API: 1. Can i, OpenAIAdapter, OpenAI hosted adapter.  Same cached-restart injection pattern as Anthropic. Open (+14 more)

### Community 2 - "Community 2"
Cohesion: 0.06
Nodes (20): TenantContext, Shared multi-tenant isolation helpers for adapters.  Native and Local-API adapte, Mix into an adapter that advertises multi_tenant_isolation='request_id'.      Ad, RequestIdIsolatedMixin, MockAdapter, MockStreamState, Mock inference adapter — for Phase 1 demos and tests.  Doesn't talk to any LLM., Simulates a streaming LLM. Configurable scripted response per request.      Capa (+12 more)

### Community 3 - "Community 3"
Cohesion: 0.07
Nodes (21): conflicts(), find_overlapping_scopes(), has_write(), _intersect_parts(), parse_scope(), patterns_intersect(), pool(), Postgres state graph client.  Provides agent registration, intention claim/relea (+13 more)

### Community 4 - "Community 4"
Cohesion: 0.06
Nodes (30): GatewayState, get_agents(), get_beliefs(), get_intentions(), get_recent_events(), lifespan(), list_sessions(), _parse_jsonb() (+22 more)

### Community 5 - "Community 5"
Cohesion: 0.09
Nodes (19): cli(), Coordinator, main(), Synapse Coordinator — event-driven LLM-mediated session-wide reasoner.  Subscrib, Long-running coordinator process. Single instance per session., AgentBelief, BeliefDivergence, beliefs_from_db_rows() (+11 more)

### Community 6 - "Community 6"
Cohesion: 0.07
Nodes (27): main(), make_coordinator_backend(), Phase 4 deliverable — coordinator agent in action.  Three scenarios: 1. **Belief, Coordinator uses Gemini Flash (free via Vertex AI)., _section(), _wait_for_ready(), main(), Phase 1 deliverable — two-agent conflict demo.  Demonstrates Synapse's core valu (+19 more)

### Community 7 - "Community 7"
Cohesion: 0.1
Nodes (30): FakeAnthropicEvent, FakeAnthropicInputJsonDelta, FakeAnthropicMessages, FakeAnthropicStream, FakeAnthropicStreamCtx, FakeAnthropicTextDelta, FakeAnthropicThinkingDelta, FakeOpenAIChoice (+22 more)

### Community 8 - "Community 8"
Cohesion: 0.08
Nodes (11): InferenceAdapter, Raised when an operation tries to act on a request_id that belongs to a     diff, TenantViolation, Protocol, Agent, agentInbox(), Bus, sessionStream() (+3 more)

### Community 9 - "Community 9"
Cohesion: 0.09
Nodes (23): Architecture at a glance, Author, code:block1 (┌─────────────────────────────────────────────────┐), code:bash (# Bring up Redis + Postgres + initial schema), code:bash (pytest sdk-python/tests/), code:block4 (synapse/), Contributing, Design principles (+15 more)

### Community 10 - "Community 10"
Cohesion: 0.12
Nodes (10): main(), Anthropic adapter live smoke test.  Verifies, against the real Anthropic API: 1., AnthropicAdapter, Anthropic hosted adapter — Sonnet/Haiku/Opus via the Anthropic Python SDK.  Impl, Cached-restart injection.          Cancels current stream, then issues a NEW req, Cached-restart injection.          Cancels current stream, then issues a NEW req, Anthropic separates `system` from `messages`. Extract it if present., Anthropic separates `system` from `messages`. Extract it if present. (+2 more)

### Community 11 - "Community 11"
Cohesion: 0.14
Nodes (8): GeminiAdapter, Gemini hosted adapter — google-genai SDK.  Same cached-restart pattern as Anthro, Gemini takes 'contents' (list) and optional 'system_instruction'.          We ac, Gemini takes 'contents' (list) and optional 'system_instruction'.          We ac, Hosted-tier adapter for Google Gemini.      Uses the google-genai SDK. With GOOG, Tests for hosted adapters — capability surface, message prep, error handling.  D, TestAdaptersImportable, TestGeminiAdapter

### Community 12 - "Community 12"
Cohesion: 0.13
Nodes (16): _build_backend(), _percentile(), `synapse bench` — standardized backend benchmark.  Workloads: - pair-coding:, run_bench(), _wait_ready(), cmd_bench(), cmd_spec_validate(), `synapse` CLI entry point.  Subcommands: - `synapse spec validate [PATH ...]` — (+8 more)

### Community 14 - "Community 14"
Cohesion: 0.1
Nodes (19): code:block1 (scope        := segment ("." segment)* [":" modifier]), code:block2 (Agent A: scope=["auth.middleware:w"]), code:block3 (Agent A: scope=["db.users.schema:r"]), code:block4 (Agent A: scope=["db.users.schema:r"]), code:block5 (Agent A: scope=["db.users.**:w"]), code:block6 (Agent A: scope=["auth.middleware:w"], blocks_others=["auth.*), Conflict Semantics, Dependency vs Conflict (+11 more)

### Community 15 - "Community 15"
Cohesion: 0.12
Nodes (16): code:bash (# Bring up Redis + Postgres with the initial schema applied), code:bash (docker compose ps), code:bash (python examples/two_agents_conflict_demo.py), code:block4 (============================================================), code:bash (docker compose down -v   # removes volumes (Postgres + Redis), code:bash (pip install pytest pytest-asyncio), examples, Expected output (+8 more)

### Community 16 - "Community 16"
Cohesion: 0.15
Nodes (14): code:bash (pip install -e .             # from this directory), code:python (import asyncio), code:bash (pip install pytest pytest-asyncio), code:block4 (synapse/), Install, Module layout, Module layout (planned), Phase 1 surface (+6 more)

### Community 17 - "Community 17"
Cohesion: 0.13
Nodes (14): Capability Flags, code:python (from typing import Protocol, AsyncIterator), Cost Reporting, Failure Modes, Implementing a New Adapter, InferenceAdapter Contract, Interface, `multi_tenant_isolation` (+6 more)

### Community 18 - "Community 18"
Cohesion: 0.14
Nodes (5): Tests for Phase 3 adapters — Ollama (local-API) and vLLM-via-Modal (native).  Al, Each tier should have characteristic overhead and isolation defaults., TestOllamaAdapter, TestPhaseThreeAdaptersImportable, TestVLLMModalAdapter

### Community 19 - "Community 19"
Cohesion: 0.19
Nodes (9): Identifies who owns a request in a multi-tenant deployment.      All four fields, Opaque handle to an in-flight generation. Adapter-specific contents., StreamHandle, _messages_to_prompt(), OllamaAdapter, Ollama local-API adapter.  Talks to a locally-running Ollama server (default htt, Local-API resume: cancel stream, restart with last context tokens.          If t, Local-API tier adapter for Ollama.      Args:         model: Ollama model tag (e (+1 more)

### Community 20 - "Community 20"
Cohesion: 0.24
Nodes (7): InferenceAdapter Protocol — see spec/adapter.md for the canonical contract., Raised when an operation is requested that the backend does not support     (e.g, Raised when an operation is requested that the backend does not support     (e.g, Token, UnsupportedCapability, RuntimeError, str

### Community 21 - "Community 21"
Cohesion: 0.15
Nodes (12): "But isn't this just X?", Co-existence Recipes, code:block1 (┌───────────────────────────────────────────────────────────), Direct Comparison, Positioning — Synapse vs MCP, A2A, LangGraph, AutoGen, Synapse + A2A, Synapse + LangGraph, Synapse + MCP (+4 more)

### Community 22 - "Community 22"
Cohesion: 0.17
Nodes (11): code:bash (npm install @synapse-protocol/sdk), code:ts (import { Agent, Bus, MockAdapter } from "@synapse-protocol/s), code:ts (const owner = { tenant_id: "acme", agent_id: "a1", session_i), code:bash (npm install), Install, Multi-tenant isolation, Quickstart, Roadmap (+3 more)

### Community 23 - "Community 23"
Cohesion: 0.27
Nodes (5): _messages_to_prompt(), vLLM-via-Modal native adapter.  Talks to a Modal-deployed vLLM engine over Modal, Connects to a deployed Modal vLLM engine via RPC.      Args:         modal_app:, Lazy-resolve the deployed Modal class. Caches across calls., VLLMModalAdapter

### Community 24 - "Community 24"
Cohesion: 0.27
Nodes (5): BackendUnavailable, Raised when the backend cannot be reached. SDK falls back to no-coordination mod, Raised when the backend cannot be reached. SDK falls back to no-coordination mod, Two auth modes:         - **API key**: pass api_key=... or set GOOGLE_API_KEY/GE, BackendCapabilities

### Community 25 - "Community 25"
Cohesion: 0.18
Nodes (10): Action Items, ADR-0002: Protocol v1.0 Freeze, Backward-compatible (allowed in 1.x), Backward-incompatible (requires 2.0), Consequences, Context, Decision, Evolution Rules (+2 more)

### Community 26 - "Community 26"
Cohesion: 0.22
Nodes (5): Modal serverless GPU engine for Synapse native-tier adapter.  Uses real **vLLM**, Stateful container hosting a real vLLM AsyncLLMEngine.      Each container insta, Stateful container hosting a transformers-based engine.      Named `VLLMEngine`, smoke_test(), VLLMEngine

### Community 27 - "Community 27"
Cohesion: 0.2
Nodes (9): bench, code:bash (synapse bench --backend mock --workload conflict-heavy), Pending backends, Recorded results, Recorded results (this session), Run, Synapse Benchmark Results, What the report contains (+1 more)

### Community 28 - "Community 28"
Cohesion: 0.2
Nodes (9): Action Items, ADR-0001: v1.0 Architecture Baseline, Components, Consequences, Context, Decision, Key Mechanisms, Resolved Open Questions (+1 more)

### Community 29 - "Community 29"
Cohesion: 0.2
Nodes (9): Architecture, code:bash (# 1. Bring up infrastructure (from repo root)), code:bash (python examples/two_agents_conflict_demo.py), code:block3 (Browser (Next.js, :3000)), Layout, Production deploy notes (later), Run it, Synapse Observability UI (+1 more)

### Community 30 - "Community 30"
Cohesion: 0.22
Nodes (8): code:bash (pip install -e sdk-python), Endpoints, Environment, Implementation notes, REST, Run, Synapse Observability Gateway, WebSocket

### Community 31 - "Community 31"
Cohesion: 0.22
Nodes (8): code:block1 (spec/), Layout, Reading Order, Synapse Protocol Specification, The Eight Message Types, The Seven Message Types, Validation, Versioning

### Community 32 - "Community 32"
Cohesion: 0.43
Nodes (7): main(), make_gemini(), make_mock(), make_vllm_modal(), Phase 3 deliverable — three agents, three backend tiers, one protocol.  Demonstr, _section(), _wait_for_ready()

### Community 33 - "Community 33"
Cohesion: 0.25
Nodes (7): Before opening a PR, code:bash (# Bring up Redis + Postgres), Contributing to Synapse, How to propose a new message type, License, Local development, Repository conventions

### Community 34 - "Community 34"
Cohesion: 0.4
Nodes (3): CrewAI integration — wrap a CrewAI Task or any callable so that its execution pa, Monkey-patch the task's execute methods to emit Synapse messages., _wrap_task_object()

## Knowledge Gaps
- **265 isolated node(s):** `Anthropic adapter live smoke test.  Verifies, against the real Anthropic API: 1.`, `Phase 4 deliverable — coordinator agent in action.  Three scenarios: 1. **Belief`, `Coordinator uses Gemini Flash (free via Vertex AI).`, `Phase 5 deliverable — L3 semantic router in action.  L3 picks up messages that L`, `Phase 3 deliverable — three agents, three backend tiers, one protocol.  Demonstr` (+260 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **27 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `InferenceAdapter` connect `Community 8` to `Community 0`, `Community 1`, `Community 2`, `Community 5`, `Community 10`, `Community 11`, `Community 19`, `Community 20`, `Community 23`, `Community 24`?**
  _High betweenness centrality (0.100) - this node is a cross-community bridge._
- **Why does `StateGraph` connect `Community 6` to `Community 0`, `Community 1`, `Community 32`, `Community 3`, `Community 4`, `Community 5`, `Community 12`?**
  _High betweenness centrality (0.097) - this node is a cross-community bridge._
- **Why does `MockAdapter` connect `Community 2` to `Community 32`, `Community 1`, `Community 0`, `Community 6`, `Community 8`, `Community 12`, `Community 18`, `Community 19`, `Community 20`, `Community 24`?**
  _High betweenness centrality (0.076) - this node is a cross-community bridge._
- **Are the 18 inferred relationships involving `MockAdapter` (e.g. with `RequestIdIsolatedMixin` and `InferenceAdapter`) actually correct?**
  _`MockAdapter` has 18 INFERRED edges - model-reasoned connections that need verification._
- **Are the 20 inferred relationships involving `Agent` (e.g. with `InferenceAdapter` and `Bus`) actually correct?**
  _`Agent` has 20 INFERRED edges - model-reasoned connections that need verification._
- **Are the 18 inferred relationships involving `Bus` (e.g. with `Coordinator` and `GatewayState`) actually correct?**
  _`Bus` has 18 INFERRED edges - model-reasoned connections that need verification._
- **Are the 24 inferred relationships involving `BackendUnavailable` (e.g. with `BackendCapabilities` and `AnthropicAdapter`) actually correct?**
  _`BackendUnavailable` has 24 INFERRED edges - model-reasoned connections that need verification._