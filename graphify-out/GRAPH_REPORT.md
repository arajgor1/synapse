# Graph Report - .  (2026-05-07)

## Corpus Check
- 122 files · ~71,216 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1211 nodes · 2529 edges · 40 communities detected
- Extraction: 57% EXTRACTED · 43% INFERRED · 0% AMBIGUOUS · INFERRED: 1096 edges (avg confidence: 0.59)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Coordinator + Bench Workloads|Coordinator + Bench Workloads]]
- [[_COMMUNITY_InferenceAdapter Protocol Surface|InferenceAdapter Protocol Surface]]
- [[_COMMUNITY_Architecture Decisions + Adapter Tiers|Architecture Decisions + Adapter Tiers]]
- [[_COMMUNITY_Demo Entry Points|Demo Entry Points]]
- [[_COMMUNITY_Architecture Baseline Rationale|Architecture Baseline Rationale]]
- [[_COMMUNITY_Hermes Integration|Hermes Integration]]
- [[_COMMUNITY_Multi-Tenant Isolation|Multi-Tenant Isolation]]
- [[_COMMUNITY_Adapter Family Landscape|Adapter Family Landscape]]
- [[_COMMUNITY_Two-Agent Conflict Demo|Two-Agent Conflict Demo]]
- [[_COMMUNITY_Coordinator Event Handlers|Coordinator Event Handlers]]
- [[_COMMUNITY_Modal Sandbox Runner|Modal Sandbox Runner]]
- [[_COMMUNITY_Scope Matcher|Scope Matcher]]
- [[_COMMUNITY_Anthropic Test Fakes|Anthropic Test Fakes]]
- [[_COMMUNITY_Protocol Freeze + v0.2 ADR-0003|Protocol Freeze + v0.2 ADR-0003]]
- [[_COMMUNITY_Framework Integrations Surface|Framework Integrations Surface]]
- [[_COMMUNITY_Gateway WebSocket State|Gateway WebSocket State]]
- [[_COMMUNITY_L3 Semantic Router|L3 Semantic Router]]
- [[_COMMUNITY_CrewAI Integration|CrewAI Integration]]
- [[_COMMUNITY_Synapse CLI|Synapse CLI]]
- [[_COMMUNITY_vLLM Modal Engine|vLLM Modal Engine]]
- [[_COMMUNITY_TS SDK Surface|TS SDK Surface]]
- [[_COMMUNITY_Inject + Replay|Inject + Replay]]
- [[_COMMUNITY_Bus + Streams|Bus + Streams]]
- [[_COMMUNITY_State Graph Persistence|State Graph Persistence]]
- [[_COMMUNITY_Conflict Semantics|Conflict Semantics]]
- [[_COMMUNITY_Paperclip Integration|Paperclip Integration]]
- [[_COMMUNITY_LangGraph Integration|LangGraph Integration]]
- [[_COMMUNITY_Stale-Base Overwrite Fix|Stale-Base Overwrite Fix]]
- [[_COMMUNITY_Migrations + Schema|Migrations + Schema]]
- [[_COMMUNITY_Smart Router Phases|Smart Router Phases]]
- [[_COMMUNITY_Audit Pipeline (v0.2)|Audit Pipeline (v0.2)]]
- [[_COMMUNITY_Universal Intend SDK (v0.2)|Universal Intend SDK (v0.2)]]
- [[_COMMUNITY_Cluster 40|Cluster 40]]
- [[_COMMUNITY_Cluster 41|Cluster 41]]
- [[_COMMUNITY_Cluster 42|Cluster 42]]
- [[_COMMUNITY_Cluster 55|Cluster 55]]
- [[_COMMUNITY_Cluster 56|Cluster 56]]
- [[_COMMUNITY_Cluster 57|Cluster 57]]
- [[_COMMUNITY_Cluster 58|Cluster 58]]
- [[_COMMUNITY_Cluster 59|Cluster 59]]

## God Nodes (most connected - your core abstractions)
1. `StateGraph` - 95 edges
2. `InferenceAdapter` - 82 edges
3. `Bus` - 80 edges
4. `Router` - 60 edges
5. `BackendCapabilities` - 54 edges
6. `BackendUnavailable` - 52 edges
7. `Conflict` - 51 edges
8. `StreamHandle` - 50 edges
9. `MockAdapter` - 48 edges
10. `MessageType` - 44 edges

## Surprising Connections (you probably didn't know these)
- `Synapse integration for Hermes Agent (NousResearch).  Hermes is a single-agent f` --uses--> `Agent`  [INFERRED]
  sdk-python\synapse\integrations\hermes_integration.py → sdk-python\synapse\agent.py
- `Map a Hermes tool call to a Synapse scope claim.      Convention:       file ops` --uses--> `Agent`  [INFERRED]
  sdk-python\synapse\integrations\hermes_integration.py → sdk-python\synapse\agent.py
- `Install runtime hooks into Hermes' tool dispatch path.      Returns a status dic` --uses--> `Agent`  [INFERRED]
  sdk-python\synapse\integrations\hermes_integration.py → sdk-python\synapse\agent.py
- `Register an additional Synapse agent in the same session.      Used for multi-ag` --uses--> `Agent`  [INFERRED]
  sdk-python\synapse\integrations\hermes_integration.py → sdk-python\synapse\agent.py
- `Raised inside a wrapped Hermes tool dispatch when CONFLICT arrives.` --uses--> `Agent`  [INFERRED]
  sdk-python\synapse\integrations\hermes_integration.py → sdk-python\synapse\agent.py

## Hyperedges (group relationships)
- **Synapse Core runtime stack** —  [EXTRACTED 1.00]
- **Framework integrations** —  [EXTRACTED 1.00]
- **Synapse v1.0 protocol message types** —  [EXTRACTED 1.00]
- **v0.2 strategic decisions (locked set)** — v02roadmap_decision_envelopes_canonical, v02roadmap_decision_byo_llm, v02roadmap_decision_audit_first, v02roadmap_decision_openinference_substrate, v02roadmap_decision_universal_sdk, v02roadmap_adr_0003 [INFERRED 1.00]
- **v0.2 demo gallery (5 use cases)** — v02roadmap_demo_instagram, v02roadmap_demo_ecommerce, v02roadmap_demo_marketing, v02roadmap_demo_data_analysis, v02roadmap_demo_oss_stress [INFERRED 1.00]
- **v0.2 5-week shipping plan** — v02roadmap_week1, v02roadmap_week2, v02roadmap_week3, v02roadmap_week4, v02roadmap_week5 [INFERRED 1.00]
- **The eight envelope/message types of Synapse v1.0** — msg_thought, msg_intention, msg_pivot, msg_belief, msg_block, msg_conflict, msg_resolution, msg_cost_report [INFERRED 1.00]
- **Three-tier adapter abstraction (Native/Local-API/Hosted)** — tier_native, tier_local_api, tier_hosted [INFERRED 1.00]
- **Three-step conflict decision: pattern intersection, rw modifiers, blocks_others exclusive claim** — concept_scope_matching, concept_rw_modifier, concept_blocks_others [INFERRED 1.00]
- **v0.2 strategic decisions (ADR-0003)** —  [INFERRED 1.00]
- **Rejected alternatives in ADR-0003** —  [INFERRED 1.00]
- **Framework integration wrappers** —  [INFERRED 1.00]

## Communities

### Community 0 - "Coordinator + Bench Workloads"
Cohesion: 0.04
Nodes (108): BaseModel, `synapse bench` — standardized backend benchmark.  Workloads: - pair-coding:, Synapse Coordinator — event-driven LLM-mediated session-wide reasoner.  Subscrib, Long-running coordinator process. Single instance per session., Enum, Phase 4 deliverable — coordinator agent in action.  Three scenarios: 1. **Belief, Coordinator uses Gemini Flash (free via Vertex AI)., CrewAI-style product-dev demo using synapse_task integration.  This example show (+100 more)

### Community 1 - "InferenceAdapter Protocol Surface"
Cohesion: 0.04
Nodes (72): BackendUnavailable, InferenceAdapter, InferenceAdapter Protocol — see spec/adapter.md for the canonical contract., Opaque handle to an in-flight generation. Adapter-specific contents., Raised when the backend cannot be reached. SDK falls back to no-coordination mod, Raised when an operation is requested that the backend does not support     (e.g, StreamHandle, Token (+64 more)

### Community 2 - "Architecture Decisions + Adapter Tiers"
Cohesion: 0.03
Nodes (104): Hosted adapter tier, Local-API adapter tier, Native adapter tier, ADR-1 JSON Schema for protocol, ADR-2 Redis Streams as message bus, ADR-3 Postgres + JSONB for state graph, ADR-4 Three-tier filtering rules->SQL->LLM, ADR-5 Event-driven coordinator (+96 more)

### Community 3 - "Demo Entry Points"
Cohesion: 0.04
Nodes (38): main(), make_coordinator_backend(), _section(), _wait_for_ready(), _extract_url_field_name(), main(), _make_backend(), _print_table() (+30 more)

### Community 4 - "Architecture Baseline Rationale"
Cohesion: 0.03
Nodes (75): Will revisit: L3 router cost at scale, Will revisit: mid-thinking injection, Will revisit: vLLM KV append API stability, ADR-0001 v1.0 Components, Append-and-continue primary mechanism, Backend-aware routing, Multi-tenant isolation in adapter contract, Three-tier urgency (+67 more)

### Community 5 - "Hermes Integration"
Cohesion: 0.06
Nodes (34): HermesSynapseConflict, install_hermes_synapse_hooks(), Synapse integration for Hermes Agent (NousResearch).  Hermes is a single-agent f, Install runtime hooks into Hermes' tool dispatch path.      Returns a status dic, Register an additional Synapse agent in the same session.      Used for multi-ag, Raised inside a wrapped Hermes tool dispatch when CONFLICT arrives., Wrap a Hermes tool dispatch with Synapse coordination.      Args:         tool_n, Map a Hermes tool call to a Synapse scope claim.      Convention:       file ops (+26 more)

### Community 6 - "Multi-Tenant Isolation"
Cohesion: 0.07
Nodes (25): Identifies who owns a request in a multi-tenant deployment.      All four fields, Raised when an operation tries to act on a request_id that belongs to a     diff, TenantContext, TenantViolation, Shared multi-tenant isolation helpers for adapters.  Native and Local-API adapte, Mix into an adapter that advertises multi_tenant_isolation='request_id'.      Ad, RequestIdIsolatedMixin, MockAdapter (+17 more)

### Community 7 - "Adapter Family Landscape"
Cohesion: 0.04
Nodes (57): A2A (cross-vendor agent interop), Aadit Rajgor, Anthropic adapter, Gemini adapter, Mock adapter, Ollama adapter, OpenAI adapter, Standardized adapter test suite (+49 more)

### Community 8 - "Two-Agent Conflict Demo"
Cohesion: 0.04
Nodes (50): Two-Agents Conflict Demo (Phase 1 deliverable), L2 conflict detection (SQL + Python scope matcher), Pre-execution gate (blocking=True drains inbox), Demo Prerequisites: Docker Desktop, Python 3.11+, Synapse Examples README, Fresh random session ID rationale, One-time setup (docker compose up, pip install -e sdk-python), two_agents_conflict_demo.py (+42 more)

### Community 9 - "Coordinator Event Handlers"
Cohesion: 0.09
Nodes (18): cli(), Coordinator, main(), AgentBelief, BeliefDivergence, beliefs_from_db_rows(), detect_divergences(), Belief divergence detection.  When multiple agents assert different values for t (+10 more)

### Community 10 - "Modal Sandbox Runner"
Cohesion: 0.06
Nodes (41): app_data_analysis(), app_instagram(), _common_setup_script(), fetch_docs(), fetch_integration_docs(), product_dev(), product_dev_openclaw(), product_dev_paperclip() (+33 more)

### Community 11 - "Scope Matcher"
Cohesion: 0.08
Nodes (15): conflicts(), find_overlapping_scopes(), has_write(), _intersect_parts(), parse_scope(), patterns_intersect(), pool(), Unit tests for spec/conflict-semantics.md.  Runs without infrastructure — pure f (+7 more)

### Community 12 - "Anthropic Test Fakes"
Cohesion: 0.1
Nodes (30): FakeAnthropicEvent, FakeAnthropicInputJsonDelta, FakeAnthropicMessages, FakeAnthropicStream, FakeAnthropicStreamCtx, FakeAnthropicTextDelta, FakeAnthropicThinkingDelta, FakeOpenAIChoice (+22 more)

### Community 13 - "Protocol Freeze + v0.2 ADR-0003"
Cohesion: 0.06
Nodes (40): Protocol v1.0 frozen at commit 7656e13, Protocol Evolution Rules, ADR-0002: Protocol v1.0 Freeze, synapse spec validate CLI, Alt A: Bundle hosted LLM, Alt B: OTel as canonical wire format, Alt C: Live-first integration (skip audit), ADR-0003: BYO-LLM, Audit-First, OpenInference (+32 more)

### Community 14 - "Framework Integrations Surface"
Cohesion: 0.06
Nodes (38): CONFLICT envelope, Frameworks unchanged - Synapse adapts to their APIs, Hermes Agent, INTENTION envelope, Modal sandbox smoke test, OpenClaw, Paperclip AI, Postgres state graph (+30 more)

### Community 15 - "Gateway WebSocket State"
Cohesion: 0.08
Nodes (22): GatewayState, get_agents(), get_beliefs(), get_intentions(), get_recent_events(), lifespan(), list_sessions(), _parse_jsonb() (+14 more)

### Community 16 - "L3 Semantic Router"
Cohesion: 0.1
Nodes (8): main(), _section(), _wait_for_ready(), L3SemanticRouter, L3Stats, TestL3Stats, TestL3Threshold, TestOpenAIAdapter

### Community 17 - "CrewAI Integration"
Cohesion: 0.1
Nodes (17): FakeCrewTask, main(), CrewAI integration — wrap a CrewAI Task or any callable so that its execution pa, Monkey-patch the task's execute methods to emit Synapse messages., Wrap a CrewAI Task (or any callable) with Synapse coordination.      Returns a f, synapse_task(), _wrap_task_object(), synapse_node() (+9 more)

### Community 18 - "Synapse CLI"
Cohesion: 0.14
Nodes (14): _percentile(), run_bench(), _wait_ready(), cmd_bench(), cmd_spec_validate(), `synapse` CLI entry point.  Subcommands: - `synapse spec validate [PATH ...]` —, _iter_inputs(), _load_schemas() (+6 more)

### Community 19 - "vLLM Modal Engine"
Cohesion: 0.25
Nodes (4): Modal serverless GPU engine for Synapse native-tier adapter.  Uses real **vLLM**, Stateful container hosting a real vLLM AsyncLLMEngine.      Each container insta, smoke_test(), VLLMEngine

### Community 20 - "TS SDK Surface"
Cohesion: 0.47
Nodes (5): agents, beliefs, blocks, events, intentions

### Community 22 - "Inject + Replay"
Cohesion: 0.67
Nodes (2): main(), runScenario()

### Community 24 - "Bus + Streams"
Cohesion: 1.0
Nodes (1): Synapse router — L1 (rules) + L2 (SQL conflict) for Phase 1.  L3 (semantic relev

### Community 25 - "State Graph Persistence"
Cohesion: 1.0
Nodes (1): synapse CLI — `synapse spec validate`, `synapse bench`, and friends.

### Community 26 - "Conflict Semantics"
Cohesion: 1.0
Nodes (1): Synapse framework integrations.  These are NOT inference adapters (those wrap LL

### Community 30 - "Paperclip Integration"
Cohesion: 1.0
Nodes (2): Router (L1 rules, L2 SQL, L3 LLM-mediated), stale_base_overwrite detection

### Community 32 - "LangGraph Integration"
Cohesion: 1.0
Nodes (1): Combined confidence + source-rank score, 0..1.          observed > inferred > as

### Community 34 - "Stale-Base Overwrite Fix"
Cohesion: 1.0
Nodes (1): Stream tokens via vLLM's native async generator.          Yields dicts: {"delta"

### Community 36 - "Migrations + Schema"
Cohesion: 1.0
Nodes (1): Construct a fresh envelope with a new ULID and current timestamp.

### Community 37 - "Smart Router Phases"
Cohesion: 1.0
Nodes (1): Documented happy path: a sequence of content_block_delta events with         tex

### Community 38 - "Audit Pipeline (v0.2)"
Cohesion: 1.0
Nodes (1): Tool-use streaming sends input_json_delta. Adapter should skip         these (th

### Community 39 - "Universal Intend SDK (v0.2)"
Cohesion: 1.0
Nodes (1): Extended-thinking models emit thinking_delta. v1 adapter ignores.

### Community 40 - "Cluster 40"
Cohesion: 1.0
Nodes (1): Verify the cached-restart message structure matches the documented         promp

### Community 41 - "Cluster 41"
Cohesion: 1.0
Nodes (1): Standard openai-python chunk shape:         chunk.choices[0].delta.content -> st

### Community 42 - "Cluster 42"
Cohesion: 1.0
Nodes (1): Some chunks can have an empty choices list (rare but documented).

### Community 55 - "Cluster 55"
Cohesion: 1.0
Nodes (1): Gateway (FastAPI WebSocket + REST)

### Community 56 - "Cluster 56"
Cohesion: 1.0
Nodes (1): Observability UI (Next.js dashboard)

### Community 57 - "Cluster 57"
Cohesion: 1.0
Nodes (1): Synapse CLI

### Community 58 - "Cluster 58"
Cohesion: 1.0
Nodes (1): AutoGen framework

### Community 59 - "Cluster 59"
Cohesion: 1.0
Nodes (1): runtime README (stub)

## Knowledge Gaps
- **155 isolated node(s):** `Anthropic adapter live smoke test.  Verifies, against the real Anthropic API: 1.`, `OpenAI adapter live smoke test.  Verifies, against the real OpenAI API: 1. Can i`, `Belief divergence detection.  When multiple agents assert different values for t`, `Combined confidence + source-rank score, 0..1.          observed > inferred > as`, `Two or more agents holding distinct values for the same key.` (+150 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Inject + Replay`** (4 nodes): `main()`, `makeWriteCodeExtension()`, `runScenario()`, `real_product_dev_openclaw.mjs`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Bus + Streams`** (2 nodes): `Synapse router — L1 (rules) + L2 (SQL conflict) for Phase 1.  L3 (semantic relev`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `State Graph Persistence`** (2 nodes): `synapse CLI — `synapse spec validate`, `synapse bench`, and friends.`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Conflict Semantics`** (2 nodes): `Synapse framework integrations.  These are NOT inference adapters (those wrap LL`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Paperclip Integration`** (2 nodes): `Router (L1 rules, L2 SQL, L3 LLM-mediated)`, `stale_base_overwrite detection`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `LangGraph Integration`** (1 nodes): `Combined confidence + source-rank score, 0..1.          observed > inferred > as`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Stale-Base Overwrite Fix`** (1 nodes): `Stream tokens via vLLM's native async generator.          Yields dicts: {"delta"`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Migrations + Schema`** (1 nodes): `Construct a fresh envelope with a new ULID and current timestamp.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Smart Router Phases`** (1 nodes): `Documented happy path: a sequence of content_block_delta events with         tex`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Audit Pipeline (v0.2)`** (1 nodes): `Tool-use streaming sends input_json_delta. Adapter should skip         these (th`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Universal Intend SDK (v0.2)`** (1 nodes): `Extended-thinking models emit thinking_delta. v1 adapter ignores.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 40`** (1 nodes): `Verify the cached-restart message structure matches the documented         promp`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 41`** (1 nodes): `Standard openai-python chunk shape:         chunk.choices[0].delta.content -> st`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 42`** (1 nodes): `Some chunks can have an empty choices list (rare but documented).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 55`** (1 nodes): `Gateway (FastAPI WebSocket + REST)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 56`** (1 nodes): `Observability UI (Next.js dashboard)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 57`** (1 nodes): `Synapse CLI`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 58`** (1 nodes): `AutoGen framework`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 59`** (1 nodes): `runtime README (stub)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `StateGraph` connect `Coordinator + Bench Workloads` to `Demo Entry Points`, `Hermes Integration`, `Multi-Tenant Isolation`, `Coordinator Event Handlers`, `Scope Matcher`, `Gateway WebSocket State`, `L3 Semantic Router`, `CrewAI Integration`, `Synapse CLI`?**
  _High betweenness centrality (0.083) - this node is a cross-community bridge._
- **Why does `InferenceAdapter` connect `InferenceAdapter Protocol Surface` to `Coordinator + Bench Workloads`, `Multi-Tenant Isolation`, `Coordinator Event Handlers`, `L3 Semantic Router`, `CrewAI Integration`?**
  _High betweenness centrality (0.073) - this node is a cross-community bridge._
- **Why does `AgentBelief` connect `Coordinator Event Handlers` to `Coordinator + Bench Workloads`?**
  _High betweenness centrality (0.043) - this node is a cross-community bridge._
- **Are the 86 inferred relationships involving `StateGraph` (e.g. with `Phase 4 deliverable — coordinator agent in action.  Three scenarios: 1. **Belief` and `Coordinator uses Gemini Flash (free via Vertex AI).`) actually correct?**
  _`StateGraph` has 86 INFERRED edges - model-reasoned connections that need verification._
- **Are the 76 inferred relationships involving `InferenceAdapter` (e.g. with `Phase 4 deliverable — coordinator agent in action.  Three scenarios: 1. **Belief` and `Coordinator uses Gemini Flash (free via Vertex AI).`) actually correct?**
  _`InferenceAdapter` has 76 INFERRED edges - model-reasoned connections that need verification._
- **Are the 67 inferred relationships involving `Bus` (e.g. with `Phase 4 deliverable — coordinator agent in action.  Three scenarios: 1. **Belief` and `Coordinator uses Gemini Flash (free via Vertex AI).`) actually correct?**
  _`Bus` has 67 INFERRED edges - model-reasoned connections that need verification._
- **Are the 52 inferred relationships involving `Router` (e.g. with `Phase 4 deliverable — coordinator agent in action.  Three scenarios: 1. **Belief` and `Coordinator uses Gemini Flash (free via Vertex AI).`) actually correct?**
  _`Router` has 52 INFERRED edges - model-reasoned connections that need verification._