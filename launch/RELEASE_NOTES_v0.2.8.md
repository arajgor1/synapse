# Synapse v0.2.8 — Cross-vendor cooperative app build

Released 2026-05-12.

## TL;DR

**Ten agents from ten different framework SDKs collaborated on one Synapse
session to build a Flask Todo app — and the app actually runs.**

The bundle is committed at [`bench/results/v32_app_bundle/`](../bench/results/v32_app_bundle/).
The Flask `main.py` it produced serves `GET /todos → 200` locally. The
[`envelopes.jsonl`](../bench/results/v32_app_bundle/envelopes.jsonl) is the
unified audit log: INTENTION envelopes from `autogen_default`,
`backend_engineer` (crewai), `tools` (langgraph), `agent` (pydantic_ai),
and others — all in one session.

## What's new

### Cross-vendor cooperative-build demo
- **10 vendor SDKs in one session**: AutoGen (Microsoft), CrewAI, LangGraph (LangChain), smolagents (HuggingFace), Agno, LlamaIndex, Pydantic AI, OpenAI Agents SDK, Google ADK, Hermes
- Each adapter played a different role (API Architect, Backend Engineer, Test Writer, etc.) and produced a different file in the shared app/
- Bench verifies: `py_compile main.py` succeeds + `app.test_client().get('/todos')` returns 200
- Full reproduce in <10s after `git clone`

### Convergence bench — deterministic 10/10 V1_PASS
- v26 ↔ v27 reproduced byte-for-byte: 23 intents / 9 THOUGHTs across 10 adapters
- Per-adapter intent counts match exactly across runs
- `bench/PUBLIC_BENCHMARK.md` Phase 10 has the full history (v21 → v32)

### OpenAI THOUGHT-capture parity
- `wrap_openai_for_thoughts` now emits PSEUDO_THOUGHT envelopes from `message.content` when the model has no native `reasoning` field (gpt-4o-mini, gpt-4o, gpt-4)
- Brings OpenAI route to parity with Anthropic route (which had this fallback in v0.2.7)
- 3 new regression tests in `tests/test_llm_thoughts_openai_pseudo.py`

### llama_index Workflow hook
- Now correctly patches `BaseWorkflowAgent._call_tool` and `AgentWorkflow._call_tool`
- This is the canonical hook in `llama-index-core>=0.11` for `ReActAgent.run`, `FunctionAgent.run`, `CodeActAgent.run`, `AgentWorkflow.run`
- 5 intents + 1 THOUGHT per llama_index session, deterministic

### HuggingFace deep NLA module (preview)
- New `synapse.llm_nla_hf.wrap_hf_model_for_nla()` — captures logits + attention + hidden-state norms per token
- Useful for self-hosted vLLM / HuggingFace transformer audits
- Lazy import — torch is optional, base install unaffected

### Cross-vendor cooperative-build UI
- New page `/builds/v32` — works offline (no gateway needed)
- VerdictBand (vendors × files × intents × app-runs), VendorAgentGrid (10 cards with vendor badges + direct/fallback markers), ArtifactPreview (click to view any produced file), EnvelopeTimeline (chronological INTENTIONs)
- Static-bundle API route reads `bench/results/v32_app_bundle/` directly

### Other fixes
- `bus.publish_session()` (not `bus.publish()`) — fixed silent THOUGHT drop affecting v18–v21
- Crewai validator: `main.py` must contain `from flask` + `@app.route` + `todos` + `jsonify` AND `py_compile` cleanly, else universal fallback fires
- `flask` added to Modal image install batch 1 (for v28+ app verifier)

## Carry-forward to v0.2.9

Open about what isn't yet perfect:

1. **3/10 OpenAI adapters dispatch tools with empty content** under gpt-4o-mini (langgraph, smolagents, agno). The fallback rescues the artifact but no INTENT is registered for those agents. Anthropic route doesn't have this issue (v27 was 10/10 with all intents).
2. **L2 router gate-window Redis ZADD path** — would tighten inter-process ordering; existing tests pass without it.
3. **HuggingFace deep NLA in CI** — module ships, but Modal image doesn't include torch by default.
4. **Replay over WebRTC** — UI does static replay; live replay works only when gateway is up.

## Reproduce

```bash
git clone https://github.com/arajgor1/synapse && cd synapse
pip install flask
cd bench/results/v32_app_bundle
python -c "import main; print(main.app.test_client().get('/todos').status_code)"
# → 200
```

For the convergence bench (10/10 V1_PASS), see `runtime/modal/_payloads/public_benchmark_v21.py` and the run instructions in `bench/PUBLIC_BENCHMARK.md`.

## Commits

v0.2.7 → v0.2.8 spans 28 commits across:
- `sdk-python/synapse/llm_thoughts.py` — OpenAI PSEUDO_THOUGHT
- `sdk-python/synapse/llm_nla_hf.py` — HuggingFace NLA (new module)
- `sdk-python/synapse/frameworks/llama_index.py` — Workflow hook
- `sdk-python/synapse/frameworks/langgraph.py` — dual auto-attach
- `sdk-python/synapse/agent.py` — gate-window inbox drain
- `runtime/modal/_payloads/public_benchmark_v{21..32}.py` — 12 bench iterations
- `bench/results/v32_app_bundle/` — the committed cooperative-build artifact
- `ui/src/app/builds/v32/page.tsx` + 5 new components
- `bench/PUBLIC_BENCHMARK.md` Phase 10
- `tests/test_llm_thoughts_openai_pseudo.py` — 3 new regression tests

374 tests passing.

---

🧬 **Synapse** · [Repo](https://github.com/arajgor1/synapse) · [Public benchmark](../bench/PUBLIC_BENCHMARK.md) · [v32 bundle](../bench/results/v32_app_bundle/)
