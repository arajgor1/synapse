# Graph Report - synapse  (2026-05-06)

## Corpus Check
- 45 files · ~17,610 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 459 nodes · 720 edges · 40 communities (24 shown, 16 thin omitted)
- Extraction: 68% EXTRACTED · 32% INFERRED · 0% AMBIGUOUS · INFERRED: 228 edges (avg confidence: 0.65)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `72701477`
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
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]

## God Nodes (most connected - your core abstractions)
1. `Agent` - 22 edges
2. `BackendCapabilities` - 22 edges
3. `BackendUnavailable` - 21 edges
4. `AnthropicAdapter` - 21 edges
5. `GeminiAdapter` - 21 edges
6. `Bus` - 20 edges
7. `Router` - 18 edges
8. `MockAdapter` - 18 edges
9. `conflicts()` - 17 edges
10. `StateGraph` - 17 edges

## Surprising Connections (you probably didn't know these)
- `make_mock()` --calls--> `MockAdapter`  [INFERRED]
  examples/multi_backend_demo.py → sdk-python/synapse/adapters/mock.py
- `make_gemini()` --calls--> `GeminiAdapter`  [INFERRED]
  examples/multi_backend_demo.py → sdk-python/synapse/adapters/hosted/gemini_adapter.py
- `make_vllm_modal()` --calls--> `VLLMModalAdapter`  [INFERRED]
  examples/multi_backend_demo.py → sdk-python/synapse/adapters/native/vllm_modal_adapter.py
- `main()` --calls--> `Bus`  [INFERRED]
  examples/multi_backend_demo.py → sdk-python/synapse/bus.py
- `main()` --calls--> `StateGraph`  [INFERRED]
  examples/multi_backend_demo.py → sdk-python/synapse/state.py

## Communities (40 total, 16 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.07
Nodes (21): conflicts(), find_overlapping_scopes(), has_write(), _intersect_parts(), parse_scope(), patterns_intersect(), pool(), Postgres state graph client.  Provides agent registration, intention claim/relea (+13 more)

### Community 1 - "Community 1"
Cohesion: 0.07
Nodes (22): BackendUnavailable, Opaque handle to an in-flight generation. Adapter-specific contents., Raised when the backend cannot be reached. SDK falls back to no-coordination mod, StreamHandle, Two auth modes:         - **API key**: pass api_key=... or set GOOGLE_API_KEY/GE, _messages_to_prompt(), OllamaAdapter, Ollama local-API adapter.  Talks to a locally-running Ollama server (default htt (+14 more)

### Community 2 - "Community 2"
Cohesion: 0.12
Nodes (25): BaseModel, Enum, Router, AgentRegistration, Belief, Block, Conflict, ConflictingIntention (+17 more)

### Community 3 - "Community 3"
Cohesion: 0.08
Nodes (13): AnthropicAdapter, Anthropic hosted adapter — Sonnet/Haiku/Opus via the Anthropic Python SDK.  Impl, Cached-restart injection.          Cancels current stream, then issues a NEW req, Anthropic separates `system` from `messages`. Extract it if present., Hosted-tier adapter for Anthropic.      Capability flags reflect Anthropic's str, GeminiAdapter, Gemini hosted adapter — google-genai SDK.  Same cached-restart pattern as Anthro, Gemini takes 'contents' (list) and optional 'system_instruction'.          We ac (+5 more)

### Community 4 - "Community 4"
Cohesion: 0.11
Nodes (13): agent_inbox(), Bus, Redis Streams client for the Synapse message bus.  Conventions: - Session-wide s, Single-consumer inbox reader. Caller tracks last_id., Non-blocking: read all available inbox messages since last_id and return them., Async Redis Streams wrapper with envelope serialization., Publish to the session-wide stream. Returns the Redis stream entry ID., Publish directly to a specific agent's inbox. (+5 more)

### Community 5 - "Community 5"
Cohesion: 0.09
Nodes (23): Architecture at a glance, Author, code:block1 (┌─────────────────────────────────────────────────┐), code:bash (# Bring up Redis + Postgres + initial schema), code:bash (pytest sdk-python/tests/), code:block4 (synapse/), Contributing, Design principles (+15 more)

### Community 6 - "Community 6"
Cohesion: 0.13
Nodes (12): InferenceAdapter, MockAdapter, MockStreamState, Mock inference adapter — for Phase 1 demos and tests.  Doesn't talk to any LLM., Simulates a streaming LLM. Configurable scripted response per request.      Capa, Protocol, _collect(), Tests for the mock inference adapter — the Phase 1 reference adapter. (+4 more)

### Community 7 - "Community 7"
Cohesion: 0.16
Nodes (13): InferenceAdapter Protocol — see spec/adapter.md for the canonical contract., Raised when an operation is requested that the backend does not support     (e.g, Token, UnsupportedCapability, main(), Phase 1 deliverable — two-agent conflict demo.  Demonstrates Synapse's core valu, Generic wait-for-ready: retries `connect_fn()` until it succeeds or retries exha, _section() (+5 more)

### Community 8 - "Community 8"
Cohesion: 0.1
Nodes (19): code:block1 (scope        := segment ("." segment)* [":" modifier]), code:block2 (Agent A: scope=["auth.middleware:w"]), code:block3 (Agent A: scope=["db.users.schema:r"]), code:block4 (Agent A: scope=["db.users.schema:r"]), code:block5 (Agent A: scope=["db.users.**:w"]), code:block6 (Agent A: scope=["auth.middleware:w"], blocks_others=["auth.*), Conflict Semantics, Dependency vs Conflict (+11 more)

### Community 9 - "Community 9"
Cohesion: 0.12
Nodes (16): code:bash (# Bring up Redis + Postgres with the initial schema applied), code:bash (docker compose ps), code:bash (python examples/two_agents_conflict_demo.py), code:block4 (============================================================), code:bash (docker compose down -v   # removes volumes (Postgres + Redis), code:bash (pip install pytest pytest-asyncio), examples, Expected output (+8 more)

### Community 10 - "Community 10"
Cohesion: 0.15
Nodes (6): cli(), main(), Router worker.  Consumes a session stream via consumer group 'router'. For each, Glob-style topic matching (auth.* matches auth.middleware)., topic_matches(), StateGraph

### Community 11 - "Community 11"
Cohesion: 0.17
Nodes (6): Agent, lifecycle(), Synapse Agent — the developer-facing surface.  Phase 1 surface area: register, e, Emit an INTENTION and (if blocking) wait briefly for CONFLICT/BLOCK signals., Drain inbox during the gate window, return any CONFLICT/BLOCK targeting this int, Read all inbox messages since last drain. Returns envelopes (caller dispatches b

### Community 12 - "Community 12"
Cohesion: 0.15
Nodes (14): code:bash (pip install -e .             # from this directory), code:python (import asyncio), code:bash (pip install pytest pytest-asyncio), code:block4 (synapse/), Install, Module layout, Module layout (planned), Phase 1 surface (+6 more)

### Community 13 - "Community 13"
Cohesion: 0.13
Nodes (14): Capability Flags, code:python (from typing import Protocol, AsyncIterator), Cost Reporting, Failure Modes, Implementing a New Adapter, InferenceAdapter Contract, Interface, `multi_tenant_isolation` (+6 more)

### Community 14 - "Community 14"
Cohesion: 0.15
Nodes (12): "But isn't this just X?", Co-existence Recipes, code:block1 (┌───────────────────────────────────────────────────────────), Direct Comparison, Positioning — Synapse vs MCP, A2A, LangGraph, AutoGen, Synapse + A2A, Synapse + LangGraph, Synapse + MCP (+4 more)

### Community 15 - "Community 15"
Cohesion: 0.2
Nodes (9): Action Items, ADR-0001: v1.0 Architecture Baseline, Components, Consequences, Context, Decision, Key Mechanisms, Resolved Open Questions (+1 more)

### Community 16 - "Community 16"
Cohesion: 0.25
Nodes (4): Modal serverless GPU engine for Synapse native-tier adapter.  Phase 3 ships with, Stateful container hosting a transformers-based engine.      Named `VLLMEngine`, smoke_test(), VLLMEngine

### Community 17 - "Community 17"
Cohesion: 0.33
Nodes (8): collect(), main(), make_backend(), Phase 2 deliverable — same conflict demo, real LLM (Gemini by default).  Drop-in, Pick a hosted adapter based on env. Cheap defaults.      Gemini auto-uses Vertex, Read up to N tokens from a streaming handle and return the joined text., _section(), _wait_for_ready()

### Community 18 - "Community 18"
Cohesion: 0.22
Nodes (8): code:block1 (spec/), Layout, Reading Order, Synapse Protocol Specification, The Eight Message Types, The Seven Message Types, Validation, Versioning

### Community 19 - "Community 19"
Cohesion: 0.43
Nodes (7): main(), make_gemini(), make_mock(), make_vllm_modal(), Phase 3 deliverable — three agents, three backend tiers, one protocol.  Demonstr, _section(), _wait_for_ready()

### Community 20 - "Community 20"
Cohesion: 0.25
Nodes (7): Before opening a PR, code:bash (# Bring up Redis + Postgres), Contributing to Synapse, How to propose a new message type, License, Local development, Repository conventions

## Knowledge Gaps
- **155 isolated node(s):** `Phase 3 deliverable — three agents, three backend tiers, one protocol.  Demonstr`, `Phase 1 deliverable — two-agent conflict demo.  Demonstrates Synapse's core valu`, `Phase 2 deliverable — same conflict demo, real LLM (Gemini by default).  Drop-in`, `Pick a hosted adapter based on env. Cheap defaults.      Gemini auto-uses Vertex`, `Read up to N tokens from a streaming handle and return the joined text.` (+150 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **16 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `StateGraph` connect `Community 10` to `Community 0`, `Community 2`, `Community 7`, `Community 11`, `Community 17`, `Community 19`?**
  _High betweenness centrality (0.099) - this node is a cross-community bridge._
- **Why does `Agent` connect `Community 11` to `Community 2`, `Community 4`, `Community 6`, `Community 7`, `Community 10`, `Community 17`, `Community 19`?**
  _High betweenness centrality (0.071) - this node is a cross-community bridge._
- **Why does `Bus` connect `Community 4` to `Community 2`, `Community 7`, `Community 10`, `Community 11`, `Community 17`, `Community 19`?**
  _High betweenness centrality (0.057) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `Agent` (e.g. with `InferenceAdapter` and `Bus`) actually correct?**
  _`Agent` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 20 inferred relationships involving `BackendCapabilities` (e.g. with `StreamHandle` and `Token`) actually correct?**
  _`BackendCapabilities` has 20 INFERRED edges - model-reasoned connections that need verification._
- **Are the 18 inferred relationships involving `BackendUnavailable` (e.g. with `BackendCapabilities` and `AnthropicAdapter`) actually correct?**
  _`BackendUnavailable` has 18 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `AnthropicAdapter` (e.g. with `BackendUnavailable` and `InferenceAdapter`) actually correct?**
  _`AnthropicAdapter` has 13 INFERRED edges - model-reasoned connections that need verification._