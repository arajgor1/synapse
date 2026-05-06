# Graph Report - synapse  (2026-05-06)

## Corpus Check
- 71 files · ~28,755 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 683 nodes · 1110 edges · 65 communities (40 shown, 25 thin omitted)
- Extraction: 69% EXTRACTED · 31% INFERRED · 0% AMBIGUOUS · INFERRED: 339 edges (avg confidence: 0.66)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `f1c6e843`
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
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 64|Community 64]]

## God Nodes (most connected - your core abstractions)
1. `Agent` - 29 edges
2. `Bus` - 28 edges
3. `BackendUnavailable` - 27 edges
4. `StateGraph` - 25 edges
5. `BackendCapabilities` - 24 edges
6. `GeminiAdapter` - 24 edges
7. `Coordinator` - 23 edges
8. `AnthropicAdapter` - 23 edges
9. `L3SemanticRouter` - 21 edges
10. `MockAdapter` - 20 edges

## Surprising Connections (you probably didn't know these)
- `make_coordinator_backend()` --calls--> `GeminiAdapter`  [INFERRED]
  examples/coordinator_demo.py → sdk-python/synapse/adapters/hosted/gemini_adapter.py
- `main()` --calls--> `Bus`  [INFERRED]
  examples/coordinator_demo.py → sdk-python/synapse/bus.py
- `main()` --calls--> `StateGraph`  [INFERRED]
  examples/coordinator_demo.py → sdk-python/synapse/state.py
- `main()` --calls--> `Agent`  [INFERRED]
  examples/coordinator_demo.py → sdk-python/synapse/agent.py
- `main()` --calls--> `MockAdapter`  [INFERRED]
  examples/coordinator_demo.py → sdk-python/synapse/adapters/mock.py

## Communities (65 total, 25 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.06
Nodes (43): BaseModel, Enum, cli(), main(), Router worker.  Consumes a session stream via consumer group 'router'. For each, Glob-style topic matching (auth.* matches auth.middleware)., Router, topic_matches() (+35 more)

### Community 1 - "Community 1"
Cohesion: 0.07
Nodes (21): conflicts(), find_overlapping_scopes(), has_write(), _intersect_parts(), parse_scope(), patterns_intersect(), pool(), Postgres state graph client.  Provides agent registration, intention claim/relea (+13 more)

### Community 2 - "Community 2"
Cohesion: 0.06
Nodes (21): main(), Phase 1 deliverable — two-agent conflict demo.  Demonstrates Synapse's core valu, Generic wait-for-ready: retries `connect_fn()` until it succeeds or retries exha, _section(), _wait_for_postgres_ready(), _wait_for_ready(), GatewayState, lifespan() (+13 more)

### Community 3 - "Community 3"
Cohesion: 0.1
Nodes (30): FakeAnthropicEvent, FakeAnthropicInputJsonDelta, FakeAnthropicMessages, FakeAnthropicStream, FakeAnthropicStreamCtx, FakeAnthropicTextDelta, FakeAnthropicThinkingDelta, FakeOpenAIChoice (+22 more)

### Community 4 - "Community 4"
Cohesion: 0.08
Nodes (17): main(), make_gemini(), make_mock(), make_vllm_modal(), Phase 3 deliverable — three agents, three backend tiers, one protocol.  Demonstr, _section(), _wait_for_ready(), _messages_to_prompt() (+9 more)

### Community 5 - "Community 5"
Cohesion: 0.13
Nodes (14): AgentBelief, BeliefDivergence, beliefs_from_db_rows(), detect_divergences(), Belief divergence detection.  When multiple agents assert different values for t, Two or more agents holding distinct values for the same key., Structural equality, with float fuzz., Group beliefs by key. Within each key, find sets of agents with     distinct val (+6 more)

### Community 6 - "Community 6"
Cohesion: 0.11
Nodes (10): L3SemanticRouter, L3Stats, L3 semantic router — uses an LLM to decide cross-domain relevance for messages t, L3 only operates on THOUGHT and BELIEF messages; INTENTION/CONFLICT         alre, Adaptive threshold based on cost feedback.          If recent L3-driven actions, Subscribes to a session stream and runs LLM-based routing for     messages that, L3 router unit tests — JSON parsing, candidate filter, threshold logic.  No live, The adjust_threshold logic on a fake router. We instantiate a partial     L3Sema (+2 more)

### Community 7 - "Community 7"
Cohesion: 0.09
Nodes (23): Architecture at a glance, Author, code:block1 (┌─────────────────────────────────────────────────┐), code:bash (# Bring up Redis + Postgres + initial schema), code:bash (pytest sdk-python/tests/), code:block4 (synapse/), Contributing, Design principles (+15 more)

### Community 8 - "Community 8"
Cohesion: 0.15
Nodes (11): cli(), Coordinator, main(), Synapse Coordinator — event-driven LLM-mediated session-wide reasoner.  Subscrib, Long-running coordinator process. Single instance per session., main(), make_coordinator_backend(), Phase 4 deliverable — coordinator agent in action.  Three scenarios: 1. **Belief (+3 more)

### Community 9 - "Community 9"
Cohesion: 0.1
Nodes (19): code:block1 (scope        := segment ("." segment)* [":" modifier]), code:block2 (Agent A: scope=["auth.middleware:w"]), code:block3 (Agent A: scope=["db.users.schema:r"]), code:block4 (Agent A: scope=["db.users.schema:r"]), code:block5 (Agent A: scope=["db.users.**:w"]), code:block6 (Agent A: scope=["auth.middleware:w"], blocks_others=["auth.*), Conflict Semantics, Dependency vs Conflict (+11 more)

### Community 10 - "Community 10"
Cohesion: 0.14
Nodes (8): AnthropicAdapter, Anthropic hosted adapter — Sonnet/Haiku/Opus via the Anthropic Python SDK.  Impl, Cached-restart injection.          Cancels current stream, then issues a NEW req, Cached-restart injection.          Cancels current stream, then issues a NEW req, Anthropic separates `system` from `messages`. Extract it if present., Anthropic separates `system` from `messages`. Extract it if present., Hosted-tier adapter for Anthropic.      Capability flags reflect Anthropic's str, TestAnthropicAdapter

### Community 11 - "Community 11"
Cohesion: 0.15
Nodes (7): GeminiAdapter, Gemini hosted adapter — google-genai SDK.  Same cached-restart pattern as Anthro, Gemini takes 'contents' (list) and optional 'system_instruction'.          We ac, Hosted-tier adapter for Google Gemini.      Uses the google-genai SDK. With GOOG, Tests for hosted adapters — capability surface, message prep, error handling.  D, TestAdaptersImportable, TestGeminiAdapter

### Community 12 - "Community 12"
Cohesion: 0.18
Nodes (16): get_agents(), get_beliefs(), get_intentions(), get_recent_events(), list_sessions(), _parse_jsonb(), Synapse Observability Gateway.  A FastAPI service that: - Subscribes to a sessio, List session_ids that have any agents registered. (+8 more)

### Community 13 - "Community 13"
Cohesion: 0.17
Nodes (12): MockAdapter, Simulates a streaming LLM. Configurable scripted response per request.      Capa, main(), Phase 5 deliverable — L3 semantic router in action.  L3 picks up messages that L, _section(), _wait_for_ready(), _collect(), Tests for the mock inference adapter — the Phase 1 reference adapter. (+4 more)

### Community 14 - "Community 14"
Cohesion: 0.12
Nodes (16): code:bash (# Bring up Redis + Postgres with the initial schema applied), code:bash (docker compose ps), code:bash (python examples/two_agents_conflict_demo.py), code:block4 (============================================================), code:bash (docker compose down -v   # removes volumes (Postgres + Redis), code:bash (pip install pytest pytest-asyncio), examples, Expected output (+8 more)

### Community 15 - "Community 15"
Cohesion: 0.15
Nodes (14): code:bash (pip install -e .             # from this directory), code:python (import asyncio), code:bash (pip install pytest pytest-asyncio), code:block4 (synapse/), Install, Module layout, Module layout (planned), Phase 1 surface (+6 more)

### Community 16 - "Community 16"
Cohesion: 0.13
Nodes (14): Capability Flags, code:python (from typing import Protocol, AsyncIterator), Cost Reporting, Failure Modes, Implementing a New Adapter, InferenceAdapter Contract, Interface, `multi_tenant_isolation` (+6 more)

### Community 17 - "Community 17"
Cohesion: 0.2
Nodes (5): OpenAIAdapter, OpenAI hosted adapter.  Same cached-restart injection pattern as Anthropic. Open, Hosted-tier adapter for OpenAI., adapter(), TestOpenAIAdapter

### Community 19 - "Community 19"
Cohesion: 0.21
Nodes (8): Opaque handle to an in-flight generation. Adapter-specific contents., StreamHandle, _messages_to_prompt(), OllamaAdapter, Ollama local-API adapter.  Talks to a locally-running Ollama server (default htt, Local-API resume: cancel stream, restart with last context tokens.          If t, Local-API tier adapter for Ollama.      Args:         model: Ollama model tag (e, Verify Ollama is reachable and the model is available.

### Community 20 - "Community 20"
Cohesion: 0.27
Nodes (6): InferenceAdapter Protocol — see spec/adapter.md for the canonical contract., Raised when an operation is requested that the backend does not support     (e.g, Token, UnsupportedCapability, RuntimeError, str

### Community 21 - "Community 21"
Cohesion: 0.15
Nodes (12): "But isn't this just X?", Co-existence Recipes, code:block1 (┌───────────────────────────────────────────────────────────), Direct Comparison, Positioning — Synapse vs MCP, A2A, LangGraph, AutoGen, Synapse + A2A, Synapse + LangGraph, Synapse + MCP (+4 more)

### Community 22 - "Community 22"
Cohesion: 0.2
Nodes (9): Action Items, ADR-0001: v1.0 Architecture Baseline, Components, Consequences, Context, Decision, Key Mechanisms, Resolved Open Questions (+1 more)

### Community 23 - "Community 23"
Cohesion: 0.2
Nodes (9): Architecture, code:bash (# 1. Bring up infrastructure (from repo root)), code:bash (python examples/two_agents_conflict_demo.py), code:block3 (Browser (Next.js, :3000)), Layout, Production deploy notes (later), Run it, Synapse Observability UI (+1 more)

### Community 24 - "Community 24"
Cohesion: 0.25
Nodes (4): Modal serverless GPU engine for Synapse native-tier adapter.  Phase 3 ships with, Stateful container hosting a transformers-based engine.      Named `VLLMEngine`, smoke_test(), VLLMEngine

### Community 25 - "Community 25"
Cohesion: 0.36
Nodes (4): BackendUnavailable, Raised when the backend cannot be reached. SDK falls back to no-coordination mod, Two auth modes:         - **API key**: pass api_key=... or set GOOGLE_API_KEY/GE, BackendCapabilities

### Community 26 - "Community 26"
Cohesion: 0.22
Nodes (4): InferenceAdapter, MockStreamState, Mock inference adapter — for Phase 1 demos and tests.  Doesn't talk to any LLM., Protocol

### Community 27 - "Community 27"
Cohesion: 0.33
Nodes (8): collect(), main(), make_backend(), Phase 2 deliverable — same conflict demo, real LLM (Gemini by default).  Drop-in, Pick a hosted adapter based on env. Cheap defaults.      Gemini auto-uses Vertex, Read up to N tokens from a streaming handle and return the joined text., _section(), _wait_for_ready()

### Community 28 - "Community 28"
Cohesion: 0.22
Nodes (8): code:bash (pip install -e sdk-python), Endpoints, Environment, Implementation notes, REST, Run, Synapse Observability Gateway, WebSocket

### Community 29 - "Community 29"
Cohesion: 0.22
Nodes (8): code:block1 (spec/), Layout, Reading Order, Synapse Protocol Specification, The Eight Message Types, The Seven Message Types, Validation, Versioning

### Community 30 - "Community 30"
Cohesion: 0.25
Nodes (7): Before opening a PR, code:bash (# Bring up Redis + Postgres), Contributing to Synapse, How to propose a new message type, License, Local development, Repository conventions

## Knowledge Gaps
- **215 isolated node(s):** `Phase 4 deliverable — coordinator agent in action.  Three scenarios: 1. **Belief`, `Coordinator uses Gemini Flash (free via Vertex AI).`, `Phase 5 deliverable — L3 semantic router in action.  L3 picks up messages that L`, `Phase 3 deliverable — three agents, three backend tiers, one protocol.  Demonstr`, `Phase 1 deliverable — two-agent conflict demo.  Demonstrates Synapse's core valu` (+210 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **25 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `StateGraph` connect `Community 2` to `Community 0`, `Community 1`, `Community 4`, `Community 6`, `Community 8`, `Community 13`, `Community 27`?**
  _High betweenness centrality (0.116) - this node is a cross-community bridge._
- **Why does `AnthropicAdapter` connect `Community 10` to `Community 8`, `Community 11`, `Community 17`, `Community 19`, `Community 20`, `Community 25`, `Community 26`, `Community 27`?**
  _High betweenness centrality (0.085) - this node is a cross-community bridge._
- **Why does `Coordinator` connect `Community 8` to `Community 0`, `Community 26`, `Community 2`, `Community 5`?**
  _High betweenness centrality (0.082) - this node is a cross-community bridge._
- **Are the 17 inferred relationships involving `Agent` (e.g. with `InferenceAdapter` and `Bus`) actually correct?**
  _`Agent` has 17 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `Bus` (e.g. with `Coordinator` and `GatewayState`) actually correct?**
  _`Bus` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 24 inferred relationships involving `BackendUnavailable` (e.g. with `BackendCapabilities` and `AnthropicAdapter`) actually correct?**
  _`BackendUnavailable` has 24 INFERRED edges - model-reasoned connections that need verification._
- **Are the 16 inferred relationships involving `StateGraph` (e.g. with `Coordinator` and `GatewayState`) actually correct?**
  _`StateGraph` has 16 INFERRED edges - model-reasoned connections that need verification._