# Graph Report - synapse  (2026-05-06)

## Corpus Check
- 55 files · ~24,228 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 621 nodes · 1035 edges · 53 communities (28 shown, 25 thin omitted)
- Extraction: 68% EXTRACTED · 32% INFERRED · 0% AMBIGUOUS · INFERRED: 332 edges (avg confidence: 0.66)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `a086d13b`
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
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 52|Community 52]]

## God Nodes (most connected - your core abstractions)
1. `Agent` - 29 edges
2. `BackendUnavailable` - 27 edges
3. `Bus` - 26 edges
4. `BackendCapabilities` - 24 edges
5. `GeminiAdapter` - 24 edges
6. `Coordinator` - 23 edges
7. `StateGraph` - 23 edges
8. `AnthropicAdapter` - 23 edges
9. `L3SemanticRouter` - 21 edges
10. `MockAdapter` - 20 edges

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

## Communities (53 total, 25 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.06
Nodes (38): BaseModel, Coordinator, Long-running coordinator process. Single instance per session., Enum, Agent, lifecycle(), Synapse Agent — the developer-facing surface.  Phase 1 surface area: register, e, Emit an INTENTION and (if blocking) wait briefly for CONFLICT/BLOCK signals. (+30 more)

### Community 1 - "Community 1"
Cohesion: 0.07
Nodes (21): conflicts(), find_overlapping_scopes(), has_write(), _intersect_parts(), parse_scope(), patterns_intersect(), pool(), Postgres state graph client.  Provides agent registration, intention claim/relea (+13 more)

### Community 2 - "Community 2"
Cohesion: 0.07
Nodes (19): main(), Phase 5 deliverable — L3 semantic router in action.  L3 picks up messages that L, _section(), _wait_for_ready(), AnthropicAdapter, Anthropic hosted adapter — Sonnet/Haiku/Opus via the Anthropic Python SDK.  Impl, Cached-restart injection.          Cancels current stream, then issues a NEW req, Cached-restart injection.          Cancels current stream, then issues a NEW req (+11 more)

### Community 3 - "Community 3"
Cohesion: 0.07
Nodes (15): OpenAIAdapter, OpenAI hosted adapter.  Same cached-restart injection pattern as Anthropic. Open, Hosted-tier adapter for OpenAI., L3SemanticRouter, L3Stats, L3 semantic router — uses an LLM to decide cross-domain relevance for messages t, L3 only operates on THOUGHT and BELIEF messages; INTENTION/CONFLICT         alre, Adaptive threshold based on cost feedback.          If recent L3-driven actions (+7 more)

### Community 4 - "Community 4"
Cohesion: 0.1
Nodes (30): FakeAnthropicEvent, FakeAnthropicInputJsonDelta, FakeAnthropicMessages, FakeAnthropicStream, FakeAnthropicStreamCtx, FakeAnthropicTextDelta, FakeAnthropicThinkingDelta, FakeOpenAIChoice (+22 more)

### Community 5 - "Community 5"
Cohesion: 0.08
Nodes (21): main(), make_coordinator_backend(), Phase 4 deliverable — coordinator agent in action.  Three scenarios: 1. **Belief, Coordinator uses Gemini Flash (free via Vertex AI)., _section(), _wait_for_ready(), collect(), main() (+13 more)

### Community 6 - "Community 6"
Cohesion: 0.09
Nodes (16): cli(), main(), Synapse Coordinator — event-driven LLM-mediated session-wide reasoner.  Subscrib, agent_inbox(), Bus, Redis Streams client for the Synapse message bus.  Conventions: - Session-wide s, Single-consumer inbox reader. Caller tracks last_id., Non-blocking: read all available inbox messages since last_id and return them. (+8 more)

### Community 7 - "Community 7"
Cohesion: 0.13
Nodes (14): AgentBelief, BeliefDivergence, beliefs_from_db_rows(), detect_divergences(), Belief divergence detection.  When multiple agents assert different values for t, Two or more agents holding distinct values for the same key., Structural equality, with float fuzz., Group beliefs by key. Within each key, find sets of agents with     distinct val (+6 more)

### Community 8 - "Community 8"
Cohesion: 0.11
Nodes (16): Raised when an operation is requested that the backend does not support     (e.g, Token, UnsupportedCapability, main(), Phase 1 deliverable — two-agent conflict demo.  Demonstrates Synapse's core valu, Generic wait-for-ready: retries `connect_fn()` until it succeeds or retries exha, _section(), _wait_for_postgres_ready() (+8 more)

### Community 9 - "Community 9"
Cohesion: 0.09
Nodes (23): Architecture at a glance, Author, code:block1 (┌─────────────────────────────────────────────────┐), code:bash (# Bring up Redis + Postgres + initial schema), code:bash (pytest sdk-python/tests/), code:block4 (synapse/), Contributing, Design principles (+15 more)

### Community 10 - "Community 10"
Cohesion: 0.1
Nodes (19): code:block1 (scope        := segment ("." segment)* [":" modifier]), code:block2 (Agent A: scope=["auth.middleware:w"]), code:block3 (Agent A: scope=["db.users.schema:r"]), code:block4 (Agent A: scope=["db.users.schema:r"]), code:block5 (Agent A: scope=["db.users.**:w"]), code:block6 (Agent A: scope=["auth.middleware:w"], blocks_others=["auth.*), Conflict Semantics, Dependency vs Conflict (+11 more)

### Community 11 - "Community 11"
Cohesion: 0.18
Nodes (12): Opaque handle to an in-flight generation. Adapter-specific contents., StreamHandle, MockAdapter, MockStreamState, Mock inference adapter — for Phase 1 demos and tests.  Doesn't talk to any LLM., Simulates a streaming LLM. Configurable scripted response per request.      Capa, _collect(), Tests for the mock inference adapter — the Phase 1 reference adapter. (+4 more)

### Community 12 - "Community 12"
Cohesion: 0.12
Nodes (16): code:bash (# Bring up Redis + Postgres with the initial schema applied), code:bash (docker compose ps), code:bash (python examples/two_agents_conflict_demo.py), code:block4 (============================================================), code:bash (docker compose down -v   # removes volumes (Postgres + Redis), code:bash (pip install pytest pytest-asyncio), examples, Expected output (+8 more)

### Community 13 - "Community 13"
Cohesion: 0.15
Nodes (14): code:bash (pip install -e .             # from this directory), code:python (import asyncio), code:bash (pip install pytest pytest-asyncio), code:block4 (synapse/), Install, Module layout, Module layout (planned), Phase 1 surface (+6 more)

### Community 14 - "Community 14"
Cohesion: 0.13
Nodes (14): Capability Flags, code:python (from typing import Protocol, AsyncIterator), Cost Reporting, Failure Modes, Implementing a New Adapter, InferenceAdapter Contract, Interface, `multi_tenant_isolation` (+6 more)

### Community 15 - "Community 15"
Cohesion: 0.14
Nodes (5): Tests for Phase 3 adapters — Ollama (local-API) and vLLM-via-Modal (native).  Al, Each tier should have characteristic overhead and isolation defaults., TestOllamaAdapter, TestPhaseThreeAdaptersImportable, TestVLLMModalAdapter

### Community 16 - "Community 16"
Cohesion: 0.15
Nodes (12): "But isn't this just X?", Co-existence Recipes, code:block1 (┌───────────────────────────────────────────────────────────), Direct Comparison, Positioning — Synapse vs MCP, A2A, LangGraph, AutoGen, Synapse + A2A, Synapse + LangGraph, Synapse + MCP (+4 more)

### Community 17 - "Community 17"
Cohesion: 0.27
Nodes (5): _messages_to_prompt(), vLLM-via-Modal native adapter.  Talks to a Modal-deployed vLLM engine over Modal, Connects to a deployed Modal vLLM engine via RPC.      Args:         modal_app:, Lazy-resolve the deployed Modal class. Caches across calls., VLLMModalAdapter

### Community 18 - "Community 18"
Cohesion: 0.24
Nodes (6): _messages_to_prompt(), OllamaAdapter, Ollama local-API adapter.  Talks to a locally-running Ollama server (default htt, Local-API resume: cancel stream, restart with last context tokens.          If t, Local-API tier adapter for Ollama.      Args:         model: Ollama model tag (e, Verify Ollama is reachable and the model is available.

### Community 19 - "Community 19"
Cohesion: 0.2
Nodes (9): Action Items, ADR-0001: v1.0 Architecture Baseline, Components, Consequences, Context, Decision, Key Mechanisms, Resolved Open Questions (+1 more)

### Community 20 - "Community 20"
Cohesion: 0.36
Nodes (4): BackendUnavailable, Raised when the backend cannot be reached. SDK falls back to no-coordination mod, Two auth modes:         - **API key**: pass api_key=... or set GOOGLE_API_KEY/GE, BackendCapabilities

### Community 21 - "Community 21"
Cohesion: 0.22
Nodes (8): code:block1 (spec/), Layout, Reading Order, Synapse Protocol Specification, The Eight Message Types, The Seven Message Types, Validation, Versioning

### Community 22 - "Community 22"
Cohesion: 0.43
Nodes (7): main(), make_gemini(), make_mock(), make_vllm_modal(), Phase 3 deliverable — three agents, three backend tiers, one protocol.  Demonstr, _section(), _wait_for_ready()

### Community 23 - "Community 23"
Cohesion: 0.25
Nodes (3): InferenceAdapter, InferenceAdapter Protocol — see spec/adapter.md for the canonical contract., Protocol

### Community 24 - "Community 24"
Cohesion: 0.25
Nodes (7): Before opening a PR, code:bash (# Bring up Redis + Postgres), Contributing to Synapse, How to propose a new message type, License, Local development, Repository conventions

## Knowledge Gaps
- **199 isolated node(s):** `Phase 4 deliverable — coordinator agent in action.  Three scenarios: 1. **Belief`, `Coordinator uses Gemini Flash (free via Vertex AI).`, `Phase 5 deliverable — L3 semantic router in action.  L3 picks up messages that L`, `Phase 3 deliverable — three agents, three backend tiers, one protocol.  Demonstr`, `Phase 1 deliverable — two-agent conflict demo.  Demonstrates Synapse's core valu` (+194 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **25 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `StateGraph` connect `Community 5` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 6`, `Community 8`, `Community 22`?**
  _High betweenness centrality (0.117) - this node is a cross-community bridge._
- **Why does `AnthropicAdapter` connect `Community 2` to `Community 3`, `Community 5`, `Community 6`, `Community 8`, `Community 11`, `Community 20`, `Community 23`?**
  _High betweenness centrality (0.095) - this node is a cross-community bridge._
- **Why does `Coordinator` connect `Community 0` to `Community 7`, `Community 5`, `Community 6`, `Community 23`?**
  _High betweenness centrality (0.093) - this node is a cross-community bridge._
- **Are the 17 inferred relationships involving `Agent` (e.g. with `InferenceAdapter` and `Bus`) actually correct?**
  _`Agent` has 17 INFERRED edges - model-reasoned connections that need verification._
- **Are the 24 inferred relationships involving `BackendUnavailable` (e.g. with `BackendCapabilities` and `AnthropicAdapter`) actually correct?**
  _`BackendUnavailable` has 24 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `Bus` (e.g. with `Coordinator` and `L3Stats`) actually correct?**
  _`Bus` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 22 inferred relationships involving `BackendCapabilities` (e.g. with `StreamHandle` and `Token`) actually correct?**
  _`BackendCapabilities` has 22 INFERRED edges - model-reasoned connections that need verification._