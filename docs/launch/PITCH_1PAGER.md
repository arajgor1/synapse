# Synapse — the safety layer for multi-agent AI on shared codebases

## The problem

Two engineers, each running their own AI agent on the same repo, will silently overwrite each other's work and quietly disagree on the schema. Existing tools don't catch it.

This isn't theoretical. We measured it.

## The evidence

Hold the agent behavior constant (a real LangGraph multi-orchestrator run on a Stripe-Lite billing task, May 8 2026). Vary the coordination strategy. Measure what survives.

| Strategy | Silent loss | Loud conflicts | Belief divergences caught |
|---|---|---|---|
| No coordination | **4 of 8 files** | 0 | 0 of 3 |
| Git branches + naive merge | 0 | 4 (loud markers) | **0 of 3** |
| PR + CI with pytest in loop | 3 | 1 | **1 of 3** (only schema-shaped) |
| Shared coordination.md | 2 | 0 | 0 of 3 |
| **Synapse `MergePolicy.auto_merge`** | **0** | **4 (auto-merged)** | **3 of 3** |

**Synapse is the only strategy that catches both classes.** Source data + scoring oracle: [bench/results/v02_pitch_phase1/](../bench/results/v02_pitch_phase1/RESULTS.md).

## Why git, CI, and shared context are not enough

- **Git** is loud on textual collisions but blind to semantic. One agent writes `/api/login`, the other `/auth/login`. Branches don't overlap. CI is green. Production 500s.
- **CI** catches the 1-of-3 belief divergence that breaks tests (schema column-name mismatch). Endpoint paths and form-shape divergences are mocked away. CI also costs 5–15 min per agent iteration.
- **Shared coord files** rely on the LLM to obey. ~40% compliance observed. Brittle to prompt drift.

## What ships today

| For | Install | Time |
|---|---|---|
| Anyone with trace exports | `pip install synapse-protocol` → `synapse audit ./traces.json` | 30 seconds |
| Anyone, no install | [hosted audit tool](https://github.com/arajgor1/synapse/tree/main/launch/hosted-audit) (drop trace JSON in browser) | 10 seconds |
| Teams with PR-based AI workflows | GitHub Action `arajgor1/synapse-audit-action@v1` | 1 PR diff |
| LangGraph / CrewAI / AutoGen / Pydantic-AI / smolagents / Hermes / OpenAI Agents / Vercel AI SDK / Strands / Paperclip / OpenClaw | `pip install synapse-protocol[live]` + `synapse.install(framework="...")` | 5 min |
| Cursor / Claude Code / Codex CLI / Aider | [Claude Code BeforeTool hook](../launch/claude-code-hook/) + JSONL audit fallback | 5 min |
| AWS Bedrock / Azure AI Agent / GCP Vertex Agent Builder | `synapse audit` on the trace export (3 importers shipped) | post-hoc |

Day-1 friction for the audit path: `pip install` + run on existing trace data. Zero infrastructure required (Redis/Postgres only needed for live mode).

## Where Synapse genuinely doesn't help

- **Single-agent flows.** Pure overhead, no benefit.
- **Hierarchical orchestrator + workers.** The orchestrator pre-deconflicts file ownership; Synapse mostly observes (still catches semantic divergences via BELIEF, but lower lift).
- **Highly mocked test suites with monoculture agents.** If both agents share fixtures and mock everything, CI catches what Synapse catches.
- **Trivial textual conflicts.** Git already raises these. Synapse just catches them earlier.

## What's empirically demonstrated

- ✅ Multi-team / multi-orchestrator collisions are real and silent without coordination — May 8 multi-orch run, 4 cross-team file collisions emerged organically with zero rigging.
- ✅ Audit path covers all 3 major cloud agent services (Bedrock + Vertex + Azure trace formats), 3 conflicts detected on adversarial samples.
- ✅ SDK adapter pattern extends cleanly beyond the existing 11 frameworks — Strands adapter shipped, Semantic Kernel + ADK same-pattern.
- ✅ FS-watcher fallback gives ≥60% structural collision recall for IDE/CLI agents that don't expose hooks. Claude Code hook gives full attribution.
- ✅ Synapse + CI is strictly better than CI alone — same overhead, broader coverage.

## What's open and honest

- Belief false-positive rate not yet measured at scale. Live ground truth (multi-orch run) had zero false positives across 3 divergences caught — but n=3.
- Strands live benchmark deferred to v0.2.2 (smoke-test passed; full Modal run with AWS Strands SDK requires a design partner).
- IDE-side hooks for Cursor / Codex / VS Code Copilot remain roadmap. Today: Claude Code hook + FS-watcher fallback only.
- "How often does this collision pattern actually bite users in 2026?" — empirically real but pain sharpness varies. We're betting it gets sharper as multi-agent stacks grow. Stop-loss criteria documented in [campaign README](../bench/results/v02_pitch_phase1/RESULTS.md).

## Try it in 60 seconds

```bash
# Have a trace export from any agent run? Audit it.
pip install synapse-protocol
synapse audit ./traces.json

# Or use the hosted tool — no install:
# https://github.com/arajgor1/synapse/tree/main/launch/hosted-audit

# Live mode for your LangGraph / CrewAI / AutoGen / etc. crew:
pip install 'synapse-protocol[live]'
synapse up                     # local Redis + Postgres via docker-compose
python -c "import synapse; synapse.install(framework='langgraph')"
```

## Repo

[github.com/arajgor1/synapse](https://github.com/arajgor1/synapse) · Apache 2.0 · v0.2.1-alpha
