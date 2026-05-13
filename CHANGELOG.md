# Changelog

All notable changes to Synapse will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.8] — 2026-05-12

### Added
- **Cross-vendor cooperative-build demo**: ten different framework agents
  collaborate on one Synapse session and build a Flask Todo app that
  actually runs (`GET /todos → 200`). Bundle committed at
  `bench/results/v32_app_bundle/`.
- **HuggingFace deep NLA module** (`synapse.llm_nla_hf`): captures logits +
  attention + hidden-states per token for self-hosted transformers. Lazy
  import; torch is optional.
- **`/builds/v32` UI page**: works offline; reads the static bundle and
  shows verdict band + 10-vendor agent grid + artifact preview + envelope
  timeline + reproduce block.
- **PSEUDO_THOUGHT capture for OpenAI**: `wrap_openai_for_thoughts` now
  falls back to `message.content` when no native `reasoning` field is
  present (parity with the Anthropic wrapper).
- 3 new regression tests in `tests/test_llm_thoughts_openai_pseudo.py`.
- Universal fallback for cross-framework cooperative builds in the v30+
  bench payloads.
- Standard governance files: `CODE_OF_CONDUCT.md`, `SECURITY.md`,
  `SUPPORT.md`, `CHANGELOG.md`, `CONTRIBUTORS.md`, `.github/` templates.

### Fixed
- **Silent THOUGHT-envelope drop**: `Bus.publish()` did not exist (only
  `publish_session()` and `publish_inbox()`). The Anthropic wrapper had
  been calling the wrong name, the AttributeError was caught at
  debug-level, and every captured THOUGHT was being dropped across
  v0.2.6, v0.2.7. Fixed in `synapse/llm_thoughts.py`.
- **`llama_index` adapter on `>=0.11`**: Workflow rewrite removed the old
  dispatch path. The adapter now patches `BaseWorkflowAgent._call_tool`
  and `AgentWorkflow._call_tool` — the canonical hook for `ReActAgent`,
  `FunctionAgent`, `CodeActAgent`, and `AgentWorkflow`.
- **LangGraph nested ToolNode callbacks**: top-level `RunnableConfig.callbacks`
  did not propagate into nested tool dispatches. Now uses
  `register_configure_hook(inheritable=True)`.
- **OpenAI Agents SDK reliable tool dispatch**: now uses
  `ModelSettings(tool_choice="required")` to guarantee tool calls.
- **L2 router gate-window determinism**: when local fast-path query returns
  empty, the agent now drains the inbox briefly for router-emitted
  CONFLICTs before returning.
- **Bench verifier trailing-prose handling**: regex now extracts the
  Python function body and stops at the first dedented non-Python line,
  preventing `exec()` from blowing up on trailing "DONE" tokens.

### Changed
- README rewritten with v0.2.8 cooperative-build hero and accurate badges.
- Repo structure cleaned of internal planning docs, launch drafts, and
  cost-disclosure lines (moved to `.internal/`, gitignored).

### Benchmarks
- **10/10 V1_PASS deterministic** in the convergence bench, byte-for-byte
  reproducible across runs (v26 ↔ v27: 23 intents / 9 THOUGHTs match
  per-adapter).
- 374 tests passing.

[Full v0.2.8 release notes →](https://github.com/arajgor1/synapse/releases/tag/v0.2.8)

---

## [0.2.7] — 2026-05-12

### Added
- LLM thought capture (`synapse.llm_thoughts`) for Anthropic, OpenAI, and
  JSONL streams from Codex CLI / Claude Code transcripts.
- 8/10 V1_PASS end-to-end product builds across framework adapters
  (in v19.1).
- 3/3 NLA-extended builds with extended thinking enabled.

### Fixed
- L2 router gate-window deterministic conflict routing.
- LLM thought-capture timing fix (background-task ordering).

---

## [0.2.6] — 2026-05-11

### Added
- 8-track release: adapter fixes for all framework adapters,
  LLM thought capture, v15-v19 bench iterations.

### Fixed
- LangGraph `create_react_agent.ainvoke` bypass of handler callbacks.
- pydantic_ai Modal end-to-end with `scope_from_args` config.

---

## [0.2.5] — 2026-05-10

### Added
- 13/13 organic end-to-end framework runs on Modal.
- OpenClaw 13th adapter integration (TypeScript SDK).
- REST API + MCP surfaces.
- Claude Code skills as a deployment surface.

---

## [0.2.4] — 2026-05-10

### Added
- REST API.
- Real MCP-client validation.
- IDE smoke tests.
- Claude Code skills.

---

## [0.2.3] — 2026-05-09

### Added
- 12 framework adapters + OTel live import.
- AgenticFlict benchmark (F1 = 0.865 on 5,408 paired PRs).
- 324 tests passing.

---

## [0.2.2-alpha] — 2026-05-09

### Added
- Zero-infra mode (in-memory bus + auto-SQLite + auto-spawned L2 router).
- Per-task ContextVar agent attribution (race-free under `asyncio.gather`).
- 271 tests passing.
- 8 framework adapters confirmed real-SDK working.

---

## [0.2.1-alpha] — 2026-05-08

Initial public-alpha tag.

---

## [0.2.0-alpha] — 2026-05-08

First tagged release.
