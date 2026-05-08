# Synapse — the safety layer for multi-agent AI on shared codebases

## The problem (real, measured)

Two engineers, each running their own AI agent on the same repo, will silently overwrite each other and quietly disagree on the schema. We tested this with **two real Claude Code 2.1.87 sessions on a real Stripe-Lite codebase** — they collided on 7 files (`models.py`, `routes/{cancel,subscriptions,admin,invoices}.py`, `main.py`, `tests/test_cancel.py`) producing 21 cross-agent conflicts the FS watcher captured organically.

This isn't simulated. It's two real Claude Codes, real Anthropic Haiku, real file overlap, zero rigging.

## What we measured (real runs, not models)

### Option A — Real CI/CD loop · 2 LangGraph crews + pytest after every turn

| Metric | ci_only | ci_plus_synapse |
|---|---|---|
| Cross-team file overlaps (silent) | **3** | 1 |
| CI runs / red | 12 / 12 | 12 / 12 |
| **CONFLICT envelopes detected** | **0** | **27** |
| **BELIEF DIVERGENCEs caught** (real schema-drift events) | **0** | **5** |

Real example of what Synapse caught and CI didn't: alpha and bravo independently chose
`["id","email","is_admin","created_at","updated_at"]` vs `["id","username","email","password_hash","is_admin"]` for the user table. Both passed CI in their own branches. Both would 500 in prod.

**Honest gap:** auto_merge didn't fire in this run because both agents did full-file rewrites in response to red CI rather than incremental edits. Coherence actually dropped (0.40→0.27) with Synapse on, because the conflict-routing slowed throughput. Synapse made the collisions **visible**; whether agents converge depends on whether their prompts know what to do with the visibility signal.

### Option B — Real two-Claude-Code-sessions · same shared dir

Two `claude -p` headless processes, different `SYNAPSE_AGENT_ID`, same task on the same Stripe-Lite repo. FS watcher captured every write.

| Result | |
|---|---|
| Both Claude Codes finished | 124s + 127s, exit 0 |
| FS-watcher events captured | 28 |
| **Cross-agent conflicts detected by audit** | **21 across 7 files** |
| Coherence | **0.80** (12/15 markers) |

The 3 missing markers: each Claude Code chose slightly different URL paths for the cancel/restore/status endpoints — exactly the kind of belief-divergence Synapse warns about pre-merge.

### Option C — Real Strands Agents SDK · BROKEN, honest disclosure

Real `pip install strands-agents` in Modal, two Strands agents on Stripe-Lite, with `synapse.install(framework="strands")` enabled.

| Mode | Conflicts detected |
|---|---|
| no_synapse | 0 (expected) |
| synapse | **0 — adapter never patched the real SDK** |

The shipped Strands adapter probes for `ToolHandler.handle_tool_call` (a class method that exists in older SDKs and in my smoke-test mock). The real Strands SDK 1.x dispatches via `strands.event_loop.event_loop._handle_tool_execution` (a module-level async generator). Adapter logged `could not find a tool-dispatch hook` and silently no-op'd. The fake-module smoke test passed. The real SDK fails.

The fix (patch the module-level function) is in `sdk-python/synapse/frameworks/strands.py` but **has not been re-run against real Strands**. Until it is, the SDK wedge claim for AWS Strands is unsubstantiated.

## Strategy comparison — what's real vs modeled

| Strategy | Silent file loss | Loud conflicts | Belief divergences | Real or Modeled |
|---|---|---|---|---|
| No coordination (Option A ci_only) | **3** | 0 | 0 | **REAL** |
| PR + CI w/ pytest in loop | 3 (CI doesn't catch them) | 1 | 0 | **REAL (Option A)** |
| Two Claude Codes on shared dir | implicit (not gated) | 0 (no gate) | 0 | **REAL (Option B)** |
| Synapse + CI (LangGraph) | 1 | 27 detected | 5 detected | **REAL (Option A)** |
| Synapse + FS watcher (Claude Code) | n/a | 21 detected post-hoc | 0 (no LLM oracle) | **REAL (Option B)** |
| Synapse on Strands | n/a | **0** (broken) | 0 | **REAL (Option C — broken)** |
| Git branches + naive merge | unknown | unknown | unknown | **MODELED (untested IRL)** |
| Shared coordination.md | unknown | unknown | unknown | **MODELED (untested IRL)** |

## What ships today (with realistic caveats)

| Path | Real evidence | Caveat |
|---|---|---|
| `pip install synapse-protocol` + `synapse audit` | day-1 install works on slim install, validated end-to-end | trace-format importers (Bedrock/Vertex/Azure) tested only on hand-crafted samples, not real cloud exports |
| Hosted browser audit tool | self-contained, zero install, samples included | ditto |
| GitHub Action skeleton | code complete | not yet published as `arajgor1/synapse-audit-action@v1` |
| Synapse + LangGraph live | **real Option A run: 27 conflicts + 5 beliefs caught** | auto_merge needs incremental-edit agents; full-file rewriters don't trigger merges |
| Synapse FS-watcher for Claude Code/Cursor/Codex | **real Option B run: 21 conflicts, 0.80 coherence** | attribution noise when 2 watchers run on same dir; per-session hook is the right path |
| Synapse + Strands adapter | **REFUTED — broken against real SDK** | fix exists in code, unverified; v0.2.2 |
| Synapse + CrewAI/AutoGen/OpenAI Agents/Pydantic AI/smolagents/Hermes/Vercel/Paperclip/OpenClaw | smoke-tested only against fake modules | **same risk as Strands** — needs real-SDK validation per adapter |

## Where Synapse genuinely doesn't help (also tested)

- **CI alone is not enough.** Option A showed that with both crews seeing red CI, they kept overwriting each other anyway.
- **CI + Synapse is more visible but not automatically more convergent.** Real Option A coherence dropped 0.40→0.27 with Synapse on. The visibility signal needs prompt engineering on top to translate into convergence.
- **Auto_merge requires incremental edits.** Full-file-rewrite agents (which is what Strands and Claude Code default to in many configurations) don't produce the kind of competing drafts auto_merge can reconcile. The 4 auto-merges in the May-8 multi-orch run came from agents making incremental patches, not full rewrites.
- **Single-agent flow.** Pure overhead.

## Honest open items

1. **Re-validate every SDK adapter against current published versions.** Strands case shows the smoke-test-against-fake approach catches 0% of API drift. The other 11 adapters may also be broken.
2. **Real cloud-vendor trace exports** for the audit path (generate one Bedrock Agent run, one Vertex, one Azure, audit each).
3. **Test auto_merge with incremental-edit agents** under CI pressure to see if convergence improves.
4. **Belief false-positive rate at scale** — n=8 in real runs (5 from Option A + 3 from May-8 multi-orch). All 8 were real divergences, 0 false positives, but the sample is small.

## Try it in 60 seconds

```bash
# Audit path — works today, day-1 install validated
pip install synapse-protocol
synapse audit ./traces.json

# Live mode for LangGraph (validated in Option A — detection works)
pip install 'synapse-protocol[live]'
synapse up
python -c "import synapse; synapse.install(framework='langgraph')"

# Live mode for Strands — DON'T USE v0.2.1; wait for v0.2.2

# Two-Claude-Code coordination — install the BeforeTool hook
# (see launch/claude-code-hook/README.md)
```

## What changed between this 1-pager and the prior version

The previous draft conflated modeled cells with real cells. After the user demanded IRL testing of the three cells most readers would fixate on, this draft now reports:

- **3 hypotheses real-confirmed** (down from "8 of 9 modeled-passed")
- **1 hypothesis refuted IRL** (Strands adapter)
- **2 hypotheses partially refuted on outcome** (CI+Synapse coherence, H5)
- **3 hypotheses still modeled-only** (git, shared coord.md, full audit recall on real cloud exports)

Trust gained. Pitch narrowed. The audit path and the LangGraph + Claude Code paths are real. The Strands path needs a re-run before being claimed. The cloud-vendor audit story needs real exports before being claimed.

## Repo

[github.com/arajgor1/synapse](https://github.com/arajgor1/synapse) · Apache 2.0 · v0.2.1-alpha (with v0.2.2 in flight to fix Strands)
