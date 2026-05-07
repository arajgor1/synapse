# Graph Report - .  (2026-05-07)

## Corpus Check
- 172 files · ~100,382 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1877 nodes · 4067 edges · 46 communities detected
- Extraction: 54% EXTRACTED · 46% INFERRED · 0% AMBIGUOUS · INFERRED: 1870 edges (avg confidence: 0.59)
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
- [[_COMMUNITY_Belief Divergence|Belief Divergence]]
- [[_COMMUNITY_Inject + Replay|Inject + Replay]]
- [[_COMMUNITY_Cost Telemetry|Cost Telemetry]]
- [[_COMMUNITY_Bus + Streams|Bus + Streams]]
- [[_COMMUNITY_Conflict Semantics|Conflict Semantics]]
- [[_COMMUNITY_OpenAI Adapter|OpenAI Adapter]]
- [[_COMMUNITY_Ollama Adapter|Ollama Adapter]]
- [[_COMMUNITY_Paperclip Integration|Paperclip Integration]]
- [[_COMMUNITY_OpenClaw Integration|OpenClaw Integration]]
- [[_COMMUNITY_LangGraph Integration|LangGraph Integration]]
- [[_COMMUNITY_Migrations + Schema|Migrations + Schema]]
- [[_COMMUNITY_Universal Intend SDK (v0.2)|Universal Intend SDK (v0.2)]]
- [[_COMMUNITY_Cluster 41|Cluster 41]]
- [[_COMMUNITY_Cluster 43|Cluster 43]]
- [[_COMMUNITY_Cluster 44|Cluster 44]]
- [[_COMMUNITY_Cluster 45|Cluster 45]]
- [[_COMMUNITY_Cluster 46|Cluster 46]]
- [[_COMMUNITY_Cluster 47|Cluster 47]]
- [[_COMMUNITY_Cluster 48|Cluster 48]]
- [[_COMMUNITY_Cluster 49|Cluster 49]]
- [[_COMMUNITY_Cluster 62|Cluster 62]]
- [[_COMMUNITY_Cluster 63|Cluster 63]]
- [[_COMMUNITY_Cluster 64|Cluster 64]]
- [[_COMMUNITY_Cluster 65|Cluster 65]]
- [[_COMMUNITY_Cluster 66|Cluster 66]]

## God Nodes (most connected - your core abstractions)
1. `InferenceAdapter` - 142 edges
2. `StateGraph` - 137 edges
3. `Bus` - 113 edges
4. `MockAdapter` - 102 edges
5. `BackendCapabilities` - 85 edges
6. `Conflict` - 81 edges
7. `Router` - 79 edges
8. `AuditEvent` - 65 edges
9. `Agent` - 57 edges
10. `BackendUnavailable` - 52 edges

## Surprising Connections (you probably didn't know these)
- `Agent` --uses--> `Synapse integration for Hermes Agent (NousResearch).  Hermes is a single-agent f`  [INFERRED]
  sdk-python\synapse\agent.py → sdk-python\synapse\integrations\hermes_integration.py
- `Agent` --uses--> `Map a Hermes tool call to a Synapse scope claim.      Convention:       file ops`  [INFERRED]
  sdk-python\synapse\agent.py → sdk-python\synapse\integrations\hermes_integration.py
- `Agent` --uses--> `Install runtime hooks into Hermes' tool dispatch path.      Returns a status dic`  [INFERRED]
  sdk-python\synapse\agent.py → sdk-python\synapse\integrations\hermes_integration.py
- `Agent` --uses--> `Register an additional Synapse agent in the same session.      Used for multi-ag`  [INFERRED]
  sdk-python\synapse\agent.py → sdk-python\synapse\integrations\hermes_integration.py
- `Agent` --uses--> `Raised inside a wrapped Hermes tool dispatch when CONFLICT arrives.`  [INFERRED]
  sdk-python\synapse\agent.py → sdk-python\synapse\integrations\hermes_integration.py

## Communities

### Community 0 - "Coordinator + Bench Workloads"
Cohesion: 0.03
Nodes (177): BaseModel, `synapse bench` — standardized backend benchmark.  Workloads: - pair-coding:, _agent(), main(), ``synapse demo`` — built-in 2-agent demo workload.  Runs a self-contained scenar, One agent: emit INTENTION, sleep (simulating work), check conflicts, exit., _run(), cli() (+169 more)

### Community 1 - "InferenceAdapter Protocol Surface"
Cohesion: 0.02
Nodes (123): BackendUnavailable, InferenceAdapter, InferenceAdapter Protocol — see spec/adapter.md for the canonical contract., Opaque handle to an in-flight generation. Adapter-specific contents., Raised when the backend cannot be reached. SDK falls back to no-coordination mod, Raised when an operation is requested that the backend does not support     (e.g, StreamHandle, Token (+115 more)

### Community 2 - "Architecture Decisions + Adapter Tiers"
Cohesion: 0.02
Nodes (135): AuditConflict, detect_conflicts(), In-memory conflict detector for audit-mode events.  Replicates the live L2 route, Run the L2-style detector across an event list.      Args:         events: Audit, AuditEvent, is_write(), Normalized audit-event schema.  All trace formats (OpenInference OTel, LangSmith, One tool-call observation extracted from a trace.      Mirrors the minimal shape (+127 more)

### Community 3 - "Demo Entry Points"
Cohesion: 0.02
Nodes (122): app_data_analysis(), app_instagram(), _common_setup_script(), fetch_docs(), fetch_integration_docs(), product_dev(), product_dev_openclaw(), product_dev_paperclip() (+114 more)

### Community 4 - "Architecture Baseline Rationale"
Cohesion: 0.03
Nodes (104): Hosted adapter tier, Local-API adapter tier, Native adapter tier, ADR-1 JSON Schema for protocol, ADR-2 Redis Streams as message bus, ADR-3 Postgres + JSONB for state graph, ADR-4 Three-tier filtering rules->SQL->LLM, ADR-5 Event-driven coordinator (+96 more)

### Community 5 - "Hermes Integration"
Cohesion: 0.04
Nodes (60): divergences_for_key(), emit_belief(), list_divergences(), _persist_belief_to_state(), Public-facing belief API.  ``synapse.emit_belief()`` — one-call belief emission,, Direct upsert into the beliefs table, since the coordinator's     30s tick is to, Return all current belief divergences for the session.      Useful for inspectin, Convenience: divergence detection for a single belief key. (+52 more)

### Community 6 - "Multi-Tenant Isolation"
Cohesion: 0.04
Nodes (50): Identifies who owns a request in a multi-tenant deployment.      All four fields, Raised when an operation tries to act on a request_id that belongs to a     diff, TenantContext, TenantViolation, Shared multi-tenant isolation helpers for adapters.  Native and Local-API adapte, Mix into an adapter that advertises multi_tenant_isolation='request_id'.      Ad, RequestIdIsolatedMixin, MockAdapter (+42 more)

### Community 7 - "Adapter Family Landscape"
Cohesion: 0.04
Nodes (48): main(), make_coordinator_backend(), _section(), _wait_for_ready(), _extract_url_field_name(), main(), _make_backend(), _print_table() (+40 more)

### Community 8 - "Two-Agent Conflict Demo"
Cohesion: 0.07
Nodes (61): ABC, Enum, MergePolicy, MergeAction, MergeDecision, MergePolicy, SynapseConflict, AbortPolicy (+53 more)

### Community 9 - "Coordinator Event Handlers"
Cohesion: 0.03
Nodes (75): Will revisit: L3 router cost at scale, Will revisit: mid-thinking injection, Will revisit: vLLM KV append API stability, ADR-0001 v1.0 Components, Append-and-continue primary mechanism, Backend-aware routing, Multi-tenant isolation in adapter contract, Three-tier urgency (+67 more)

### Community 10 - "Modal Sandbox Runner"
Cohesion: 0.04
Nodes (57): A2A (cross-vendor agent interop), Aadit Rajgor, Anthropic adapter, Gemini adapter, Mock adapter, Ollama adapter, OpenAI adapter, Standardized adapter test suite (+49 more)

### Community 11 - "Scope Matcher"
Cohesion: 0.06
Nodes (31): HermesSynapseConflict, install_hermes_synapse_hooks(), Synapse integration for Hermes Agent (NousResearch).  Hermes is a single-agent f, Install runtime hooks into Hermes' tool dispatch path.      Returns a status dic, Register an additional Synapse agent in the same session.      Used for multi-ag, Raised inside a wrapped Hermes tool dispatch when CONFLICT arrives., Wrap a Hermes tool dispatch with Synapse coordination.      Args:         tool_n, Map a Hermes tool call to a Synapse scope claim.      Convention:       file ops (+23 more)

### Community 12 - "Anthropic Test Fakes"
Cohesion: 0.04
Nodes (50): Two-Agents Conflict Demo (Phase 1 deliverable), L2 conflict detection (SQL + Python scope matcher), Pre-execution gate (blocking=True drains inbox), Demo Prerequisites: Docker Desktop, Python 3.11+, Synapse Examples README, Fresh random session ID rationale, One-time setup (docker compose up, pip install -e sdk-python), two_agents_conflict_demo.py (+42 more)

### Community 13 - "Protocol Freeze + v0.2 ADR-0003"
Cohesion: 0.05
Nodes (38): _agent_id_from_task(), _install_crewai(), CrewAI adapter for ``synapse.install(framework="crewai")``.  Wraps CrewAI's Task, Map a CrewAI Task to a scope claim.      Heuristics:       - If task.expected_ou, _scope_from_task(), _wrap_async(), _wrap_sync(), _autodetect_framework() (+30 more)

### Community 14 - "Framework Integrations Surface"
Cohesion: 0.1
Nodes (30): FakeAnthropicEvent, FakeAnthropicInputJsonDelta, FakeAnthropicMessages, FakeAnthropicStream, FakeAnthropicStreamCtx, FakeAnthropicTextDelta, FakeAnthropicThinkingDelta, FakeOpenAIChoice (+22 more)

### Community 15 - "Gateway WebSocket State"
Cohesion: 0.08
Nodes (15): conflicts(), find_overlapping_scopes(), has_write(), _intersect_parts(), parse_scope(), patterns_intersect(), pool(), Unit tests for spec/conflict-semantics.md.  Runs without infrastructure — pure f (+7 more)

### Community 16 - "L3 Semantic Router"
Cohesion: 0.06
Nodes (40): Protocol v1.0 frozen at commit 7656e13, Protocol Evolution Rules, ADR-0002: Protocol v1.0 Freeze, synapse spec validate CLI, Alt A: Bundle hosted LLM, Alt B: OTel as canonical wire format, Alt C: Live-first integration (skip audit), ADR-0003: BYO-LLM, Audit-First, OpenInference (+32 more)

### Community 17 - "CrewAI Integration"
Cohesion: 0.06
Nodes (38): CONFLICT envelope, Frameworks unchanged - Synapse adapts to their APIs, Hermes Agent, INTENTION envelope, Modal sandbox smoke test, OpenClaw, Paperclip AI, Postgres state graph (+30 more)

### Community 18 - "Synapse CLI"
Cohesion: 0.11
Nodes (16): main(), _section(), _wait_for_ready(), GatewayState, get_agents(), get_beliefs(), get_intentions(), get_recent_events() (+8 more)

### Community 19 - "vLLM Modal Engine"
Cohesion: 0.11
Nodes (24): _check_docker_available(), cmd_down(), cmd_status(), cmd_up(), _compose_cmd(), _find_compose_file(), main(), ``synapse up / down / status`` — one-command local stack lifecycle.  Wraps ``doc (+16 more)

### Community 20 - "TS SDK Surface"
Cohesion: 0.11
Nodes (15): _percentile(), run_bench(), _wait_ready(), cmd_audit(), cmd_bench(), cmd_spec_validate(), `synapse` CLI entry point.  Subcommands: - `synapse spec validate [PATH ...]` —, _iter_inputs() (+7 more)

### Community 21 - "Belief Divergence"
Cohesion: 0.12
Nodes (15): CrewAI integration — wrap a CrewAI Task or any callable so that its execution pa, Monkey-patch the task's execute methods to emit Synapse messages., Wrap a CrewAI Task (or any callable) with Synapse coordination.      Returns a f, synapse_task(), _wrap_task_object(), synapse_node(), fake_agent(), _FakeAgent (+7 more)

### Community 22 - "Inject + Replay"
Cohesion: 0.14
Nodes (12): clear(), get_internal_llm(), get_llm(), LLMConfig, Module-level LLM config — set once, read everywhere., The two-LLM split: a primary model for user-facing decisions     (auto-merge, es, Configure the LLM(s) Synapse will use for internal reasoning.      Args:, Return the primary adapter, or None if unconfigured. (+4 more)

### Community 23 - "Cost Telemetry"
Cohesion: 0.25
Nodes (4): Modal serverless GPU engine for Synapse native-tier adapter.  Uses real **vLLM**, Stateful container hosting a real vLLM AsyncLLMEngine.      Each container insta, smoke_test(), VLLMEngine

### Community 24 - "Bus + Streams"
Cohesion: 0.57
Nodes (5): agents, beliefs, blocks, events, intentions

### Community 26 - "Conflict Semantics"
Cohesion: 0.67
Nodes (2): main(), runScenario()

### Community 27 - "OpenAI Adapter"
Cohesion: 0.5
Nodes (3): _install_hermes(), Hermes adapter for ``synapse.install(framework="hermes")``.  The v0.1 ``synapse., Bootstrap the v0.1 Hermes integration via the v0.2 install path.      Runs ``ins

### Community 29 - "Ollama Adapter"
Cohesion: 1.0
Nodes (1): Synapse router — L1 (rules) + L2 (SQL conflict) for Phase 1.  L3 (semantic relev

### Community 30 - "Paperclip Integration"
Cohesion: 1.0
Nodes (1): synapse CLI — `synapse spec validate`, `synapse bench`, and friends.

### Community 31 - "OpenClaw Integration"
Cohesion: 1.0
Nodes (1): Framework-specific install hooks for ``synapse.install(framework=...)``.  Each m

### Community 32 - "LangGraph Integration"
Cohesion: 1.0
Nodes (1): Synapse framework integrations.  These are NOT inference adapters (those wrap LL

### Community 36 - "Migrations + Schema"
Cohesion: 1.0
Nodes (2): Router (L1 rules, L2 SQL, L3 LLM-mediated), stale_base_overwrite detection

### Community 39 - "Universal Intend SDK (v0.2)"
Cohesion: 1.0
Nodes (1): Combined confidence + source-rank score, 0..1.          observed > inferred > as

### Community 41 - "Cluster 41"
Cohesion: 1.0
Nodes (1): Stream tokens via vLLM's native async generator.          Yields dicts: {"delta"

### Community 43 - "Cluster 43"
Cohesion: 1.0
Nodes (1): Construct a fresh envelope with a new ULID and current timestamp.

### Community 44 - "Cluster 44"
Cohesion: 1.0
Nodes (1): Documented happy path: a sequence of content_block_delta events with         tex

### Community 45 - "Cluster 45"
Cohesion: 1.0
Nodes (1): Tool-use streaming sends input_json_delta. Adapter should skip         these (th

### Community 46 - "Cluster 46"
Cohesion: 1.0
Nodes (1): Extended-thinking models emit thinking_delta. v1 adapter ignores.

### Community 47 - "Cluster 47"
Cohesion: 1.0
Nodes (1): Verify the cached-restart message structure matches the documented         promp

### Community 48 - "Cluster 48"
Cohesion: 1.0
Nodes (1): Standard openai-python chunk shape:         chunk.choices[0].delta.content -> st

### Community 49 - "Cluster 49"
Cohesion: 1.0
Nodes (1): Some chunks can have an empty choices list (rare but documented).

### Community 62 - "Cluster 62"
Cohesion: 1.0
Nodes (1): Gateway (FastAPI WebSocket + REST)

### Community 63 - "Cluster 63"
Cohesion: 1.0
Nodes (1): Observability UI (Next.js dashboard)

### Community 64 - "Cluster 64"
Cohesion: 1.0
Nodes (1): Synapse CLI

### Community 65 - "Cluster 65"
Cohesion: 1.0
Nodes (1): AutoGen framework

### Community 66 - "Cluster 66"
Cohesion: 1.0
Nodes (1): runtime README (stub)

## Knowledge Gaps
- **256 isolated node(s):** `Anthropic adapter live smoke test.  Verifies, against the real Anthropic API: 1.`, `OpenAI adapter live smoke test.  Verifies, against the real OpenAI API: 1. Can i`, `Belief divergence detection.  When multiple agents assert different values for t`, `Combined confidence + source-rank score, 0..1.          observed > inferred > as`, `Two or more agents holding distinct values for the same key.` (+251 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Conflict Semantics`** (4 nodes): `main()`, `makeWriteCodeExtension()`, `runScenario()`, `real_product_dev_openclaw.mjs`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Ollama Adapter`** (2 nodes): `Synapse router — L1 (rules) + L2 (SQL conflict) for Phase 1.  L3 (semantic relev`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Paperclip Integration`** (2 nodes): `synapse CLI — `synapse spec validate`, `synapse bench`, and friends.`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `OpenClaw Integration`** (2 nodes): `Framework-specific install hooks for ``synapse.install(framework=...)``.  Each m`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `LangGraph Integration`** (2 nodes): `Synapse framework integrations.  These are NOT inference adapters (those wrap LL`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Migrations + Schema`** (2 nodes): `Router (L1 rules, L2 SQL, L3 LLM-mediated)`, `stale_base_overwrite detection`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Universal Intend SDK (v0.2)`** (1 nodes): `Combined confidence + source-rank score, 0..1.          observed > inferred > as`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 41`** (1 nodes): `Stream tokens via vLLM's native async generator.          Yields dicts: {"delta"`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 43`** (1 nodes): `Construct a fresh envelope with a new ULID and current timestamp.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 44`** (1 nodes): `Documented happy path: a sequence of content_block_delta events with         tex`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 45`** (1 nodes): `Tool-use streaming sends input_json_delta. Adapter should skip         these (th`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 46`** (1 nodes): `Extended-thinking models emit thinking_delta. v1 adapter ignores.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 47`** (1 nodes): `Verify the cached-restart message structure matches the documented         promp`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 48`** (1 nodes): `Standard openai-python chunk shape:         chunk.choices[0].delta.content -> st`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 49`** (1 nodes): `Some chunks can have an empty choices list (rare but documented).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 62`** (1 nodes): `Gateway (FastAPI WebSocket + REST)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 63`** (1 nodes): `Observability UI (Next.js dashboard)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 64`** (1 nodes): `Synapse CLI`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 65`** (1 nodes): `AutoGen framework`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 66`** (1 nodes): `runtime README (stub)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `InferenceAdapter` connect `InferenceAdapter Protocol Surface` to `Coordinator + Bench Workloads`, `Hermes Integration`, `Multi-Tenant Isolation`, `Protocol Freeze + v0.2 ADR-0003`, `Synapse CLI`, `Belief Divergence`, `Inject + Replay`?**
  _High betweenness centrality (0.101) - this node is a cross-community bridge._
- **Why does `StateGraph` connect `Coordinator + Bench Workloads` to `InferenceAdapter Protocol Surface`, `Multi-Tenant Isolation`, `Adapter Family Landscape`, `Scope Matcher`, `Gateway WebSocket State`, `Synapse CLI`, `TS SDK Surface`?**
  _High betweenness centrality (0.082) - this node is a cross-community bridge._
- **Why does `MockAdapter` connect `Multi-Tenant Isolation` to `Coordinator + Bench Workloads`, `InferenceAdapter Protocol Surface`, `Hermes Integration`, `Adapter Family Landscape`, `Two-Agent Conflict Demo`, `Scope Matcher`, `Synapse CLI`, `Belief Divergence`?**
  _High betweenness centrality (0.053) - this node is a cross-community bridge._
- **Are the 136 inferred relationships involving `InferenceAdapter` (e.g. with `Phase 4 deliverable — coordinator agent in action.  Three scenarios: 1. **Belief` and `Coordinator uses Gemini Flash (free via Vertex AI).`) actually correct?**
  _`InferenceAdapter` has 136 INFERRED edges - model-reasoned connections that need verification._
- **Are the 128 inferred relationships involving `StateGraph` (e.g. with `Phase 4 deliverable — coordinator agent in action.  Three scenarios: 1. **Belief` and `Coordinator uses Gemini Flash (free via Vertex AI).`) actually correct?**
  _`StateGraph` has 128 INFERRED edges - model-reasoned connections that need verification._
- **Are the 100 inferred relationships involving `Bus` (e.g. with `Phase 4 deliverable — coordinator agent in action.  Three scenarios: 1. **Belief` and `Coordinator uses Gemini Flash (free via Vertex AI).`) actually correct?**
  _`Bus` has 100 INFERRED edges - model-reasoned connections that need verification._
- **Are the 87 inferred relationships involving `MockAdapter` (e.g. with `IntentionHandle` and ```synapse.intend()`` — the universal context-manager SDK.  Wraps a tool dispatch`) actually correct?**
  _`MockAdapter` has 87 INFERRED edges - model-reasoned connections that need verification._