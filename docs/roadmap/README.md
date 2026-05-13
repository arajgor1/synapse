# Synapse Roadmap

This page describes **what's shipped, what's next, and what we're explicitly not building**.
Forward-looking only — past releases are documented in [`CHANGELOG.md`](../../CHANGELOG.md).

---

## ✅ Shipped (as of v0.2.8)

The five pillars Synapse claims to deliver are all live:

| Pillar | What it means | Status |
|---|---|---|
| **Audit** | Read existing trace exports (OTel / OpenInference / LangSmith / Bedrock / Vertex / Azure / JSONL) and surface silent collisions | ✅ `synapse audit ./traces.json` — 6 importers auto-detected |
| **Observability** | One unified envelope log across every vendor SDK; live dashboard + REST + WebSocket + MCP | ✅ Gateway + UI + WS stream + REST + MCP server live |
| **Conflict detection** | L1/L2/L3 router catches scope overlaps, stale-base overwrites, semantic divergences | ✅ Deterministic 10/10 V1_PASS across 10 adapters (v26 ↔ v27 byte-for-byte reproducible) |
| **Intent capture** | Every agent's INTENTION envelope persists with scope, action, expected outcome | ✅ Proven cross-vendor in the [v32 cooperative-build bundle](../../bench/results/v32_app_bundle/) |
| **NLA (reasoning capture)** | Capture model reasoning natively: Anthropic extended thinking, o-series reasoning, PSEUDO_THOUGHT fallback for plain models, HuggingFace logits/attention/hidden-states for self-hosted | ✅ `wrap_anthropic_for_thoughts` + `wrap_openai_for_thoughts` + `wrap_hf_model_for_nla` |

Other shipped capabilities:

- **10 Python adapters + 1 Node adapter** — AutoGen, CrewAI, LangGraph, smolagents, Agno, LlamaIndex, Pydantic AI, OpenAI Agents SDK, Google ADK, Hermes, OpenClaw (TS)
- **BYO-LLM** — `synapse.set_llm()` + `from_anthropic` / `from_openai` / `from_langchain` / `from_litellm` / `auto_llm`. Rules-only graceful degradation when unset.
- **MergePolicy** — `redirect`, `wait`, `abort`, `auto_merge`, custom subclasses
- **Universal SDK** — `synapse.intend()` async context manager + `synapse.install(framework=...)`
- **Zero-infra mode** — in-memory bus + auto-SQLite + auto-spawned L2 router; works without Redis/Postgres for a fresh user
- **MCP server** — 5 tools exposed to other agents
- **7 IDE/CLI plugins** — Cursor, Codex CLI, VS Code, Claude Code, Aider, Continue, Cline
- **Cross-vendor cooperative-build UI** at `/builds/v32` — works offline from a static bundle

---

## 🛠️ Next: v0.2.9 (carry-forward from v0.2.8)

Targeted at within ~2 weeks of v0.2.8.

| Item | What | Why |
|---|---|---|
| **OpenAI empty-tool-arg robustness** | 3 of 10 adapters (langgraph, smolagents, agno) dispatch tools with empty `content` under gpt-4o-mini. Fallback rescues the artifact but no INTENT registers for those agents. Need adapter-side validation that forces non-empty args. | Anthropic route had this issue in v0.2.7 (now fixed); OpenAI route hits the same problem at a different layer. |
| **L2 router Redis ZADD active-scope tracking** | Replace the Postgres SELECT path for active-scope detection with Redis ZADD for stricter inter-process ordering. | Existing tests pass without it; this is a tightening, not a fix. |
| **HuggingFace deep NLA exercised under torch in CI** | The module ships but Modal image doesn't include torch by default. Add an optional bench that pulls torch + runs `wrap_hf_model_for_nla` on a small HF transformer. | Proves the NLA pipeline works end-to-end on self-hosted models. |
| **Static bundle re-runner** | Make the v32 bundle re-runnable from the UI button (server reads the committed bundle, re-runs verifier, returns fresh `app_runs` verdict). | Self-service "does this still work?" proof for visitors. |

---

## 🎯 v0.3.0 — Production hardening

Targeted 6–8 weeks out.

- **Authentication on the gateway** — currently the REST API + WebSocket are auth-less. Adds JWT + per-tenant rate limits.
- **Multi-tenant UI** — org / project / session hierarchy in `/sessions`
- **Live replay over WebRTC** — current UI does static replay only; WebRTC adds peer-to-peer real-time playback
- **Production-grade `synapse audit` w/ streaming** — current `synapse audit` reads the whole trace file. Streaming mode for million-event logs.
- **Cost forecasting** — beyond per-session sum; budget-vs-actual tracking with alerting
- **TypeScript SDK adapter parity** — TS currently has OpenClaw + LangGraph.js. Add Vercel AI SDK, Mastra, Inngest.

---

## 🌅 Beyond v0.3 — exploratory

These are ideas worth scoping; not committed.

- **Vercel AI SDK adapter** (TypeScript)
- **Mastra adapter**
- **Inngest / Trigger.dev / Temporal integration** — emit envelopes from durable workflow runtimes
- **DAG visualization** for `BELIEF` divergence graphs over time
- **`synapse explain`** — LLM-mediated explanation of a session's audit trail in plain English ("here's what went wrong in session X")
- **Plug-and-play SOC2 evidence pack** — generate compliance artifact bundles from a session

---

## ❌ Things we are explicitly NOT building

- **Another agent framework** — Synapse wraps frameworks, never replaces them. If your agents work today on LangChain / CrewAI / AutoGen, they keep working.
- **A trace storage backend** — we leverage Postgres + Redis (open-source, ubiquitous). No proprietary store.
- **Cross-vendor agent-interop standard** — that's [A2A](https://github.com/a2aproject/A2A). We're complementary.
- **Tool-access standard** — that's [MCP](https://modelcontextprotocol.io). We're complementary.
- **A knowledge-graph layer** — that's [Semantica](https://github.com/Hawksight-AI/semantica) and others. We coordinate the agents that query knowledge graphs; we don't build the graphs themselves.
- **A new LLM API** — we use yours via `synapse.set_llm()`. We don't proxy, rebill, or wrap LLM providers commercially.

---

## How priorities get set

In order:

1. **Bugs reported by real users** — issue tracker is the source of truth
2. **Carry-forward items from the most recent release** (visible in [`CHANGELOG.md`](../../CHANGELOG.md))
3. **Adapter coverage** for frameworks that show up in production stacks
4. **Distribution / DX** (PyPI, npm, docs, examples) before new protocol surface

If your priority isn't here, [open an issue](https://github.com/arajgor1/synapse/issues/new/choose) or [start a discussion](https://github.com/arajgor1/synapse/discussions). The roadmap is a living doc.
