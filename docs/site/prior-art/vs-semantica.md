# Synapse vs Semantica — feature-by-feature

[Semantica](https://github.com/Hawksight-AI/semantica) is the closest open-source competitor to Synapse — both target multi-agent collision detection. Both are Apache-2.0. The two projects have made different design choices; this page is a fair-fight comparison citing source files, not marketing claims.

> Last updated for `synapse-protocol-0.2.2a4` (2026-05-09). Semantica details based on the public repo at HEAD as of the same date. **PRs welcome** if any cell becomes stale.

## Headline scoreboard

| Capability | Semantica | **Synapse** | Citation |
|---|---|---|---|
| Framework adapters shipped | 8 (Mar 2026) | **12** (autogen, langchain, langgraph, smolagents, crewai, openai_agents, pydantic_ai, agno, llama_index, google_adk, hermes, otel-live) | `synapse/frameworks/` |
| **End-to-end LLM-driven validation** | 0 cited | **10/12** sandbox-validated with real LLM calls | `bench/results/v022_real_llm_e2e_*.json` + Modal v4 |
| Zero-infra single-process mode | ✗ (requires Redis + Postgres) | ✓ in-memory bus + auto-SQLite | `synapse/bus_inmemory.py`, `synapse/state_sqlite.py` |
| One-shot live dashboard | ✗ | ✓ `synapse watch` | `synapse/cli/watch.py` |
| Per-task agent attribution under `asyncio.gather` | env-var based | ✓ ContextVar (race-free) | `synapse/agent_context.py`, `tests/test_agent_context.py` (50-task stress) |
| Active-scope fast path (no-conflict latency) | unknown — no published benchmark | ✓ **1.59ms median** (50x faster than naive gate) | `bench/LATENCY.md`, `bench/latency_microbench.py` |
| Conflict-resolution policy templates | 1 (default redirect) | **9** (redirect, wait, abort, auto_merge, no_op, queue_behind, wait_for_other, work_on_different_scope, escalate_to_human, retry_with_backoff) | `synapse/policies/templates.py` |
| Generic OpenTelemetry-live adapter | ✗ | ✓ for any framework emitting GenAI/OpenInference spans | `synapse/frameworks/otel_live.py` |
| Public benchmark F1 vs labelled dataset | ✗ | ✓ **0.865** on AgenticFlict (5,408 paired PRs) | `bench/results/agenticflict_benchmark.json` |
| Backend-agnostic state graph | Postgres only | Postgres + SQLite | `synapse/state.py`, `synapse/state_sqlite.py` |
| BYO-LLM (auto-merge needs none of vendor lock-in) | partial | ✓ Anthropic / OpenAI / Gemini / Ollama / LiteLLM bridge | `synapse/llm/`, `synapse.set_llm()` |
| Live conflict streaming (WebSocket) | ✗ | ✓ rotation-aware tail + incremental detector | `synapse/streaming/server.py` |
| Hosted demo pages a stranger can use | ✗ | ✓ 5 pages (audit, benchmark, explorer, team-health, landing) | `launch/hosted-audit/` |
| Test count on the SDK | unknown | **336+** | `sdk-python/tests/` |

## Where Semantica is ahead

- **Mature graph visualisation**: Semantica's React-based explorer has more polish than Synapse's d3-based one. Both are open-source — straightforward to port either way.
- **Production deployment templates**: Semantica ships Helm charts. Synapse ships a Docker Compose + a Modal payload. Helm-chart parity is on the Wave 3+ roadmap.
- **Brand recognition**: Semantica announced first (March 2026). Synapse is younger but moving faster (this comparison itself refreshes weekly).

## Where Synapse is decisively ahead

1. **Zero-infra mode.** A solo dev can `pip install synapse-protocol` + `synapse watch` and have a working coordination dashboard in 60 seconds with no Redis/Postgres running. Semantica's smallest install needs both. This is the single largest UX gap.
2. **Per-task attribution under load.** Synapse v0.2.2a2 introduced ContextVar-based attribution that's race-free under `asyncio.gather` (proven in `tests/test_agent_context.py` with a 50-task stress run). Env-var attribution (Semantica's pattern + pre-fix Synapse) silently collapses to last-writer-wins under concurrency. Modal v4 confirmed this fix in sandbox: `agents=['alice','bob']` for langchain/langgraph/smolagents.
3. **Latency.** 1.59ms median on the no-conflict path (the dominant production case) thanks to the active-scope fast path. Semantica has not published a number; the architecture (Redis pub/sub round-trip per emit) suggests double-digit ms minimum.
4. **Coverage.** 12 framework adapters (10 with E2E LLM validation) vs Semantica's 8. The OTel-live adapter additionally covers the long tail (Vercel AI SDK, CopilotKit, Inngest, Langroid, etc.) without requiring per-framework code.
5. **Conflict-resolution playbook.** Synapse ships 9 named policy templates including `queue_behind`, `work_on_different_scope`, `escalate_to_human`, `retry_with_backoff` — covering the patterns real users want without writing custom code. Semantica leaves resolution to the user.
6. **AgenticFlict citation.** F1 = 0.865 on 5,408 paired real-world agent PRs. First and only SOTA-by-default for that benchmark.

## How to verify these numbers yourself

```bash
git clone https://github.com/arajgor1/synapse
cd synapse
pip install -e ./sdk-python

# Latency claim — reproduces in 30 seconds
python bench/latency_microbench.py --iterations 50

# Test count — runs in 1 minute
cd sdk-python && python -m pytest -q

# AgenticFlict F1 — runs against the bundled labelled subset
python bench/agenticflict_benchmark.py
```

## What's the same

Both projects:

- Apache-2.0
- Python-first (Synapse also has a TypeScript SDK; Semantica is Python-only)
- Build on real published agent SDKs (no synthetic interfaces)
- Detect the same canonical scope-overlap conflict shape
- Emit envelopes in a stream-friendly format

The choice between them comes down to: **do you want a single-process zero-infra fast-path solution with broad framework coverage and a dashboard a stranger can use, or do you want Semantica's mature deployment story?** For solo devs, startups, and most teams under 30 engineers we believe Synapse wins. For enterprises with existing Helm + Vault deployments, Semantica may be a faster fit until Synapse's deployment templates catch up.

We will revisit this comparison every release cycle. If you are from the Semantica team and any cell is incorrect, open an issue at <https://github.com/arajgor1/synapse> and we'll update within 48 hours.
