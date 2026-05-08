# Graph Report - C:/C3/synapse  (2026-05-08)

## Corpus Check
- 278 files · ~176,223 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2309 nodes · 4764 edges · 57 communities detected
- Extraction: 57% EXTRACTED · 43% INFERRED · 0% AMBIGUOUS · INFERRED: 2051 edges (avg confidence: 0.59)
- Token cost: 60,000 input · 23,000 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Belief & Auto-Merge Core|Belief & Auto-Merge Core]]
- [[_COMMUNITY_Inference Adapters|Inference Adapters]]
- [[_COMMUNITY_Audit Conflict Detection|Audit Conflict Detection]]
- [[_COMMUNITY_Real-App Benchmarks|Real-App Benchmarks]]
- [[_COMMUNITY_TS SDK Runtime|TS SDK Runtime]]
- [[_COMMUNITY_Adapter Tiers & ADRs|Adapter Tiers & ADRs]]
- [[_COMMUNITY_MergePolicy|MergePolicy]]
- [[_COMMUNITY_Belief Divergence API|Belief Divergence API]]
- [[_COMMUNITY_v0.2 Benchmark Concepts|v0.2 Benchmark Concepts]]
- [[_COMMUNITY_Multi-Tenant Isolation|Multi-Tenant Isolation]]
- [[_COMMUNITY_Append-and-Continue Roadmap|Append-and-Continue Roadmap]]
- [[_COMMUNITY_Bench Runner & Coordinator|Bench Runner & Coordinator]]
- [[_COMMUNITY_Vendors & Brand Concepts|Vendors & Brand Concepts]]
- [[_COMMUNITY_Hermes Adapter|Hermes Adapter]]
- [[_COMMUNITY_Conflict Demo & Examples|Conflict Demo & Examples]]
- [[_COMMUNITY_CrewAI Adapter|CrewAI Adapter]]
- [[_COMMUNITY_Scope Matcher|Scope Matcher]]
- [[_COMMUNITY_Hosted Contract Tests|Hosted Contract Tests]]
- [[_COMMUNITY_Protocol Spec & Freeze|Protocol Spec & Freeze]]
- [[_COMMUNITY_Adapter Surface Concepts|Adapter Surface Concepts]]
- [[_COMMUNITY_Gateway State|Gateway State]]
- [[_COMMUNITY_synapse updown CLI|synapse up/down CLI]]
- [[_COMMUNITY_CrewAI Style Demo|CrewAI Style Demo]]
- [[_COMMUNITY_TS Belief API|TS Belief API]]
- [[_COMMUNITY_TS Anthropic Bridge|TS Anthropic Bridge]]
- [[_COMMUNITY_Coordinator Dispatch|Coordinator Dispatch]]
- [[_COMMUNITY_BYO-LLM Registry|BYO-LLM Registry]]
- [[_COMMUNITY_CLI Subcommands|CLI Subcommands]]
- [[_COMMUNITY_Multi-Orchestrator Bench|Multi-Orchestrator Bench]]
- [[_COMMUNITY_Coherence Scoring|Coherence Scoring]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 122|Community 122]]
- [[_COMMUNITY_Community 123|Community 123]]
- [[_COMMUNITY_Community 124|Community 124]]
- [[_COMMUNITY_Community 125|Community 125]]
- [[_COMMUNITY_Community 126|Community 126]]
- [[_COMMUNITY_Community 127|Community 127]]
- [[_COMMUNITY_Community 131|Community 131]]
- [[_COMMUNITY_Community 132|Community 132]]

## God Nodes (most connected - your core abstractions)
1. `StateGraph` - 163 edges
2. `Bus` - 147 edges
3. `InferenceAdapter` - 142 edges
4. `MockAdapter` - 102 edges
5. `Conflict` - 88 edges
6. `BackendCapabilities` - 85 edges
7. `Router` - 84 edges
8. `AuditEvent` - 65 edges
9. `Agent` - 60 edges
10. `Envelope` - 58 edges

## Surprising Connections (you probably didn't know these)
- `BELIEF divergence (semantic conflict)` --semantically_similar_to--> `belief_divergence kind`  [INFERRED] [semantically similar]
  bench/benchmarks.md → spec/protocol-v1.0/README.md
- `login_api_endpoint divergence` --semantically_similar_to--> `belief_divergence kind`  [INFERRED] [semantically similar]
  bench/results/v02_multi_orchestrator_20260508-141754_FINDINGS.md → spec/protocol-v1.0/README.md
- `webhook-endpoint-path divergence` --semantically_similar_to--> `belief_divergence kind`  [INFERRED] [semantically similar]
  bench/results/v02_autonomous_20260508-140012/FINDINGS.md → spec/protocol-v1.0/README.md
- `Semantic divergence case` --semantically_similar_to--> `belief_divergence kind`  [INFERRED] [semantically similar]
  docs/launch/BLOG_DRAFT.md → spec/protocol-v1.0/README.md
- `Agent` --uses--> `Synapse integration for Hermes Agent (NousResearch).  Hermes is a single-agent f`  [INFERRED]
  sdk-python\synapse\agent.py → sdk-python\synapse\integrations\hermes_integration.py

## Hyperedges (group relationships)
- **The 10 v1.0 protocol message types** — protocol_v10_agent_registration, protocol_v10_thought, protocol_v10_intention, protocol_v10_pivot, protocol_v10_belief, protocol_v10_block, protocol_v10_conflict, protocol_v10_resolution, protocol_v10_cost_report, protocol_v10_envelope [EXTRACTED 1.00]
- **The 11 framework adapters** — readme_langgraph, readme_crewai, readme_autogen, readme_openai_agents, readme_pydantic_ai, readme_smolagents, readme_vercel_ai, readme_langgraph_js, readme_hermes, readme_paperclip, readme_openclaw [EXTRACTED 1.00]
- **The 8 v0.2 benchmarks** — benchmarks_real_app_instagram, benchmarks_real_app_data_analysis, benchmarks_v02_w4_auto_merge, benchmarks_v02_w5_belief_divergence, benchmarks_v02_crewai_live, benchmarks_v02_langgraph_live, benchmarks_v02_sdlc_billing, benchmarks_v02_autonomous_observer, benchmarks_v02_multi_orchestrator [EXTRACTED 1.00]

## Communities

### Community 0 - "Belief & Auto-Merge Core"
Cohesion: 0.02
Nodes (224): BaseModel, emit_belief(), _persist_belief_to_state(), `synapse bench` — standardized backend benchmark.  Workloads: - pair-coding:, _agent(), main(), ``synapse demo`` — built-in 2-agent demo workload.  Runs a self-contained scenar, One agent: emit INTENTION, sleep (simulating work), check conflicts, exit. (+216 more)

### Community 1 - "Inference Adapters"
Cohesion: 0.03
Nodes (121): BackendUnavailable, InferenceAdapter, InferenceAdapter Protocol — see spec/adapter.md for the canonical contract., Opaque handle to an in-flight generation. Adapter-specific contents., Raised when the backend cannot be reached. SDK falls back to no-coordination mod, Raised when an operation is requested that the backend does not support     (e.g, StreamHandle, Token (+113 more)

### Community 2 - "Audit Conflict Detection"
Cohesion: 0.02
Nodes (138): AuditConflict, detect_conflicts(), In-memory conflict detector for audit-mode events.  Replicates the live L2 route, Run the L2-style detector across an event list.      Args:         events: Audit, AuditEvent, is_write(), Normalized audit-event schema.  All trace formats (OpenInference OTel, LangSmith, One tool-call observation extracted from a trace.      Mirrors the minimal shape (+130 more)

### Community 3 - "Real-App Benchmarks"
Cohesion: 0.02
Nodes (147): app_data_analysis(), app_instagram(), _common_setup_script(), fetch_docs(), fetch_integration_docs(), product_dev(), product_dev_openclaw(), product_dev_paperclip() (+139 more)

### Community 4 - "TS SDK Runtime"
Cohesion: 0.02
Nodes (48): agentIdFrom(), inferScope(), isWriteTool(), parseInput(), _sanitizePath(), sessionIdFrom(), SynapseLangGraphCallback, toolNameFrom() (+40 more)

### Community 5 - "Adapter Tiers & ADRs"
Cohesion: 0.03
Nodes (104): Hosted adapter tier, Local-API adapter tier, Native adapter tier, ADR-1 JSON Schema for protocol, ADR-2 Redis Streams as message bus, ADR-3 Postgres + JSONB for state graph, ADR-4 Three-tier filtering rules->SQL->LLM, ADR-5 Event-driven coordinator (+96 more)

### Community 6 - "MergePolicy"
Cohesion: 0.06
Nodes (66): ABC, Enum, MergePolicy, MergeAction, MergeDecision, MergePolicy, SynapseConflict, AbortPolicy (+58 more)

### Community 7 - "Belief Divergence API"
Cohesion: 0.04
Nodes (58): divergences_for_key(), list_divergences(), Public-facing belief API.  ``synapse.emit_belief()`` — one-call belief emission,, Direct upsert into the beliefs table, since the coordinator's     30s tick is to, Return all current belief divergences for the session.      Useful for inspectin, Convenience: divergence detection for a single belief key., Emit a BELIEF + run live divergence detection.      Args:         agent: agent i, AgentBelief (+50 more)

### Community 8 - "v0.2 Benchmark Concepts"
Cohesion: 0.03
Nodes (91): BELIEF divergence (semantic conflict), Coherence score, CONFLICT envelope, Synapse v0.2 Benchmark suite, INTENTION envelope, MergePolicy.redirect, real_app_data_analysis, real_app_instagram (+83 more)

### Community 9 - "Multi-Tenant Isolation"
Cohesion: 0.04
Nodes (43): Identifies who owns a request in a multi-tenant deployment.      All four fields, Raised when an operation tries to act on a request_id that belongs to a     diff, TenantContext, TenantViolation, Shared multi-tenant isolation helpers for adapters.  Native and Local-API adapte, Mix into an adapter that advertises multi_tenant_isolation='request_id'.      Ad, RequestIdIsolatedMixin, MockAdapter (+35 more)

### Community 10 - "Append-and-Continue Roadmap"
Cohesion: 0.03
Nodes (75): Will revisit: L3 router cost at scale, Will revisit: mid-thinking injection, Will revisit: vLLM KV append API stability, ADR-0001 v1.0 Components, Append-and-continue primary mechanism, Backend-aware routing, Multi-tenant isolation in adapter contract, Three-tier urgency (+67 more)

### Community 11 - "Bench Runner & Coordinator"
Cohesion: 0.05
Nodes (38): _percentile(), run_bench(), _wait_ready(), main(), make_coordinator_backend(), _section(), _wait_for_ready(), _finish() (+30 more)

### Community 12 - "Vendors & Brand Concepts"
Cohesion: 0.04
Nodes (57): A2A (cross-vendor agent interop), Aadit Rajgor, Anthropic adapter, Gemini adapter, Mock adapter, Ollama adapter, OpenAI adapter, Standardized adapter test suite (+49 more)

### Community 13 - "Hermes Adapter"
Cohesion: 0.06
Nodes (31): HermesSynapseConflict, install_hermes_synapse_hooks(), Synapse integration for Hermes Agent (NousResearch).  Hermes is a single-agent f, Install runtime hooks into Hermes' tool dispatch path.      Returns a status dic, Register an additional Synapse agent in the same session.      Used for multi-ag, Raised inside a wrapped Hermes tool dispatch when CONFLICT arrives., Wrap a Hermes tool dispatch with Synapse coordination.      Args:         tool_n, Map a Hermes tool call to a Synapse scope claim.      Convention:       file ops (+23 more)

### Community 14 - "Conflict Demo & Examples"
Cohesion: 0.04
Nodes (50): Two-Agents Conflict Demo (Phase 1 deliverable), L2 conflict detection (SQL + Python scope matcher), Pre-execution gate (blocking=True drains inbox), Demo Prerequisites: Docker Desktop, Python 3.11+, Synapse Examples README, Fresh random session ID rationale, One-time setup (docker compose up, pip install -e sdk-python), two_agents_conflict_demo.py (+42 more)

### Community 15 - "CrewAI Adapter"
Cohesion: 0.05
Nodes (38): _agent_id_from_task(), _install_crewai(), CrewAI adapter for ``synapse.install(framework="crewai")``.  Wraps CrewAI's Task, Map a CrewAI Task to a scope claim.      Heuristics:       - If task.expected_ou, _scope_from_task(), _wrap_async(), _wrap_sync(), _autodetect_framework() (+30 more)

### Community 16 - "Scope Matcher"
Cohesion: 0.08
Nodes (16): conflicts(), find_overlapping_scopes(), has_write(), _intersect_parts(), parse_scope(), patterns_intersect(), pool(), _require_asyncpg() (+8 more)

### Community 17 - "Hosted Contract Tests"
Cohesion: 0.1
Nodes (30): FakeAnthropicEvent, FakeAnthropicInputJsonDelta, FakeAnthropicMessages, FakeAnthropicStream, FakeAnthropicStreamCtx, FakeAnthropicTextDelta, FakeAnthropicThinkingDelta, FakeOpenAIChoice (+22 more)

### Community 18 - "Protocol Spec & Freeze"
Cohesion: 0.06
Nodes (40): Protocol v1.0 frozen at commit 7656e13, Protocol Evolution Rules, ADR-0002: Protocol v1.0 Freeze, synapse spec validate CLI, Alt A: Bundle hosted LLM, Alt B: OTel as canonical wire format, Alt C: Live-first integration (skip audit), ADR-0003: BYO-LLM, Audit-First, OpenInference (+32 more)

### Community 19 - "Adapter Surface Concepts"
Cohesion: 0.06
Nodes (38): CONFLICT envelope, Frameworks unchanged - Synapse adapts to their APIs, Hermes Agent, INTENTION envelope, Modal sandbox smoke test, OpenClaw, Paperclip AI, Postgres state graph (+30 more)

### Community 20 - "Gateway State"
Cohesion: 0.12
Nodes (13): GatewayState, get_agents(), get_beliefs(), get_intentions(), get_recent_events(), lifespan(), list_sessions(), _parse_jsonb() (+5 more)

### Community 21 - "synapse up/down CLI"
Cohesion: 0.11
Nodes (24): _check_docker_available(), cmd_down(), cmd_status(), cmd_up(), _compose_cmd(), _find_compose_file(), main(), ``synapse up / down / status`` — one-command local stack lifecycle.  Wraps ``doc (+16 more)

### Community 22 - "CrewAI Style Demo"
Cohesion: 0.1
Nodes (17): FakeCrewTask, main(), CrewAI integration — wrap a CrewAI Task or any callable so that its execution pa, Monkey-patch the task's execute methods to emit Synapse messages., Wrap a CrewAI Task (or any callable) with Synapse coordination.      Returns a f, synapse_task(), _wrap_task_object(), synapse_node() (+9 more)

### Community 23 - "TS Belief API"
Cohesion: 0.15
Nodes (18): divergencesForKey(), emitBelief(), listDivergences(), loadAgent(), loadRuntime(), persistBeliefToState(), readState(), beliefsFromDbRows() (+10 more)

### Community 24 - "TS Anthropic Bridge"
Cohesion: 0.11
Nodes (8): AnthropicBridgeAdapter, autoLlm(), bridgeCapabilities(), fromAnthropic(), fromOpenAI(), LangChainJSBridgeAdapter, OpenAIBridgeAdapter, VercelAIBridgeAdapter

### Community 25 - "Coordinator Dispatch"
Cohesion: 0.17
Nodes (12): cli(), Coordinator, main(), _extract_url_field_name(), main(), _make_backend(), _print_table(), _run_agent_independent() (+4 more)

### Community 26 - "BYO-LLM Registry"
Cohesion: 0.11
Nodes (16): clear(), get_internal_llm(), get_llm(), getInternalLlm(), getLlm(), isInferenceAdapter(), LLMConfig, Module-level LLM config — set once, read everywhere. (+8 more)

### Community 27 - "CLI Subcommands"
Cohesion: 0.12
Nodes (12): cmd_audit(), cmd_bench(), cmd_spec_validate(), `synapse` CLI entry point.  Subcommands: - `synapse spec validate [PATH ...]` —, _iter_inputs(), _load_schemas(), `synapse spec validate` — validate envelopes against v1.0 schemas.  Usage:   syn, Find the spec/protocol-v1.0 directory.      Tries (in order): SYNAPSE_SPEC_DIR e (+4 more)

### Community 28 - "Multi-Orchestrator Bench"
Cohesion: 0.37
Nodes (6): apply_migrations(), main(), run_one_mode(), run_orchestrator(), run_worker(), TimelineCapture

### Community 29 - "Coherence Scoring"
Cohesion: 0.38
Nodes (9): agent_step(), apply_migrations(), coherence_for_file(), llm_write(), main(), _read_or_blank(), run(), run_agent_plan() (+1 more)

### Community 30 - "Community 30"
Cohesion: 0.25
Nodes (4): Modal serverless GPU engine for Synapse native-tier adapter.  Uses real **vLLM**, Stateful container hosting a real vLLM AsyncLLMEngine.      Each container insta, smoke_test(), VLLMEngine

### Community 31 - "Community 31"
Cohesion: 0.57
Nodes (5): agents, beliefs, blocks, events, intentions

### Community 32 - "Community 32"
Cohesion: 0.48
Nodes (5): addToRemoveQueue(), dispatch(), genId(), reducer(), toast()

### Community 34 - "Community 34"
Cohesion: 0.67
Nodes (2): main(), runScenario()

### Community 35 - "Community 35"
Cohesion: 0.5
Nodes (3): _install_hermes(), Hermes adapter for ``synapse.install(framework="hermes")``.  The v0.1 ``synapse., Bootstrap the v0.1 Hermes integration via the v0.2 install path.      Runs ``ins

### Community 39 - "Community 39"
Cohesion: 1.0
Nodes (1): Synapse router — L1 (rules) + L2 (SQL conflict) for Phase 1.  L3 (semantic relev

### Community 40 - "Community 40"
Cohesion: 1.0
Nodes (1): synapse CLI — `synapse spec validate`, `synapse bench`, and friends.

### Community 41 - "Community 41"
Cohesion: 1.0
Nodes (1): Framework-specific install hooks for ``synapse.install(framework=...)``.  Each m

### Community 42 - "Community 42"
Cohesion: 1.0
Nodes (1): Synapse framework integrations.  These are NOT inference adapters (those wrap LL

### Community 51 - "Community 51"
Cohesion: 1.0
Nodes (2): Router (L1 rules, L2 SQL, L3 LLM-mediated), stale_base_overwrite detection

### Community 56 - "Community 56"
Cohesion: 1.0
Nodes (1): Combined confidence + source-rank score, 0..1.          observed > inferred > as

### Community 58 - "Community 58"
Cohesion: 1.0
Nodes (1): Stream tokens via vLLM's native async generator.          Yields dicts: {"delta"

### Community 60 - "Community 60"
Cohesion: 1.0
Nodes (1): Construct a fresh envelope with a new ULID and current timestamp.

### Community 61 - "Community 61"
Cohesion: 1.0
Nodes (1): Documented happy path: a sequence of content_block_delta events with         tex

### Community 62 - "Community 62"
Cohesion: 1.0
Nodes (1): Tool-use streaming sends input_json_delta. Adapter should skip         these (th

### Community 63 - "Community 63"
Cohesion: 1.0
Nodes (1): Extended-thinking models emit thinking_delta. v1 adapter ignores.

### Community 64 - "Community 64"
Cohesion: 1.0
Nodes (1): Verify the cached-restart message structure matches the documented         promp

### Community 65 - "Community 65"
Cohesion: 1.0
Nodes (1): Standard openai-python chunk shape:         chunk.choices[0].delta.content -> st

### Community 66 - "Community 66"
Cohesion: 1.0
Nodes (1): Some chunks can have an empty choices list (rare but documented).

### Community 122 - "Community 122"
Cohesion: 1.0
Nodes (1): Gateway (FastAPI WebSocket + REST)

### Community 123 - "Community 123"
Cohesion: 1.0
Nodes (1): Observability UI (Next.js dashboard)

### Community 124 - "Community 124"
Cohesion: 1.0
Nodes (1): Synapse CLI

### Community 125 - "Community 125"
Cohesion: 1.0
Nodes (1): AutoGen framework

### Community 126 - "Community 126"
Cohesion: 1.0
Nodes (1): runtime README (stub)

### Community 127 - "Community 127"
Cohesion: 1.0
Nodes (1): Construct a fresh envelope with a new ULID and current timestamp.

### Community 131 - "Community 131"
Cohesion: 1.0
Nodes (1): synapse.intend / intendWith

### Community 132 - "Community 132"
Cohesion: 1.0
Nodes (1): state_diff_extras

## Knowledge Gaps
- **335 isolated node(s):** `Anthropic adapter live smoke test.  Verifies, against the real Anthropic API: 1.`, `OpenAI adapter live smoke test.  Verifies, against the real OpenAI API: 1. Can i`, `Belief divergence detection.  When multiple agents assert different values for t`, `Combined confidence + source-rank score, 0..1.          observed > inferred > as`, `Two or more agents holding distinct values for the same key.` (+330 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 34`** (4 nodes): `main()`, `makeWriteCodeExtension()`, `runScenario()`, `real_product_dev_openclaw.mjs`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 39`** (2 nodes): `Synapse router — L1 (rules) + L2 (SQL conflict) for Phase 1.  L3 (semantic relev`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 40`** (2 nodes): `synapse CLI — `synapse spec validate`, `synapse bench`, and friends.`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 41`** (2 nodes): `Framework-specific install hooks for ``synapse.install(framework=...)``.  Each m`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 42`** (2 nodes): `Synapse framework integrations.  These are NOT inference adapters (those wrap LL`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 51`** (2 nodes): `Router (L1 rules, L2 SQL, L3 LLM-mediated)`, `stale_base_overwrite detection`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 56`** (1 nodes): `Combined confidence + source-rank score, 0..1.          observed > inferred > as`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 58`** (1 nodes): `Stream tokens via vLLM's native async generator.          Yields dicts: {"delta"`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 60`** (1 nodes): `Construct a fresh envelope with a new ULID and current timestamp.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 61`** (1 nodes): `Documented happy path: a sequence of content_block_delta events with         tex`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 62`** (1 nodes): `Tool-use streaming sends input_json_delta. Adapter should skip         these (th`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 63`** (1 nodes): `Extended-thinking models emit thinking_delta. v1 adapter ignores.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 64`** (1 nodes): `Verify the cached-restart message structure matches the documented         promp`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 65`** (1 nodes): `Standard openai-python chunk shape:         chunk.choices[0].delta.content -> st`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 66`** (1 nodes): `Some chunks can have an empty choices list (rare but documented).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 122`** (1 nodes): `Gateway (FastAPI WebSocket + REST)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 123`** (1 nodes): `Observability UI (Next.js dashboard)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 124`** (1 nodes): `Synapse CLI`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 125`** (1 nodes): `AutoGen framework`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 126`** (1 nodes): `runtime README (stub)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 127`** (1 nodes): `Construct a fresh envelope with a new ULID and current timestamp.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 131`** (1 nodes): `synapse.intend / intendWith`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 132`** (1 nodes): `state_diff_extras`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `InferenceAdapter` connect `Inference Adapters` to `Belief & Auto-Merge Core`, `Audit Conflict Detection`, `Belief Divergence API`, `Multi-Tenant Isolation`, `Bench Runner & Coordinator`, `CrewAI Adapter`, `Gateway State`, `CrewAI Style Demo`, `Coordinator Dispatch`, `BYO-LLM Registry`?**
  _High betweenness centrality (0.088) - this node is a cross-community bridge._
- **Why does `StateGraph` connect `Belief & Auto-Merge Core` to `Inference Adapters`, `Bench Runner & Coordinator`, `Hermes Adapter`, `Scope Matcher`, `Gateway State`, `CrewAI Style Demo`, `Coordinator Dispatch`, `Multi-Orchestrator Bench`, `Coherence Scoring`?**
  _High betweenness centrality (0.070) - this node is a cross-community bridge._
- **Why does `adapter()` connect `Inference Adapters` to `Hosted Contract Tests`?**
  _High betweenness centrality (0.051) - this node is a cross-community bridge._
- **Are the 154 inferred relationships involving `StateGraph` (e.g. with `main()` and `Phase 4 deliverable — coordinator agent in action.  Three scenarios: 1. **Belief`) actually correct?**
  _`StateGraph` has 154 INFERRED edges - model-reasoned connections that need verification._
- **Are the 133 inferred relationships involving `Bus` (e.g. with `Phase 4 deliverable — coordinator agent in action.  Three scenarios: 1. **Belief` and `Coordinator uses Gemini Flash (free via Vertex AI).`) actually correct?**
  _`Bus` has 133 INFERRED edges - model-reasoned connections that need verification._
- **Are the 136 inferred relationships involving `InferenceAdapter` (e.g. with `Phase 4 deliverable — coordinator agent in action.  Three scenarios: 1. **Belief` and `Coordinator uses Gemini Flash (free via Vertex AI).`) actually correct?**
  _`InferenceAdapter` has 136 INFERRED edges - model-reasoned connections that need verification._
- **Are the 87 inferred relationships involving `MockAdapter` (e.g. with `main()` and `_make_a_backend()`) actually correct?**
  _`MockAdapter` has 87 INFERRED edges - model-reasoned connections that need verification._