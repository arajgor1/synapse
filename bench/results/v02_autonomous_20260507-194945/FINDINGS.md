# Autonomous Observer Test — Honest Findings

**Date:** 2026-05-07
**Run dir:** `bench/results/v02_autonomous_20260507-194945/`
**Cost:** ~$0.20 LLM (3 modes × 12 turns × ~5 calls/turn × ~400 tokens)

## Headline result

| Mode | Turns | Files | Intentions | **Cross-agent collisions** | Beliefs | Elapsed |
|---|---|---|---|---|---|---|
| `no_synapse` | 12 | 34 | 0 | **1** | 0 | 120s |
| `observer` | 12 | 27 | 48 | **0** | 0 | 178s |
| `full` | 12 | 26 | 48 | **0** | 124 | **782s** |

**The autonomous orchestrator pre-deconflicted the work.** Each agent owned
their files (auth files → backend, Stripe files → integrations, UI files →
frontend, tests → qa). Across all 3 modes there was effectively zero
cross-agent overlap. So Synapse's structural conflict detection had
nothing to do.

## What this actually tells us

**This is the most honest finding of the v0.2 cycle**, and it's nuanced.

### What Synapse did NOT catch (because nothing was there to catch)
- **0 stale_base_overwrite conflicts** in observer + full modes
- **0 scope_overlap conflicts** in observer + full modes
- **0 belief divergences** even with 124 BELIEFs persisted

The reason isn't a Synapse bug — it's that a competent hierarchical
orchestrator IS the de-confliction layer. The orchestrator looks at the
"done so far" history each turn and assigns *different* work to each
worker. There's never a moment where two agents independently target
the same file.

### What Synapse DID do correctly
- **48 INTENTIONs persisted** to Postgres in observer + full modes (the
  protocol substrate works end-to-end through real autonomous agents)
- **124 BELIEFs auto-extracted** by the BYO-LLM in full mode (the
  extractor pipeline ran on every successful tool call's state_diff)
- **Zero crashes** across 3 modes × 12 turns × 4-5 worker spawns each
- **Captured complete trace data** — every event, every snapshot, every
  agent thought and tool call available for replay

### The cost surprise: 6.5x slowdown in `full` mode
Wall clock: 120s (no_synapse) → 178s (observer) → **782s (full)**.

The big jump is in `full` mode because `emit_beliefs_from_tool_results=True`
runs the BYO-LLM on every successful tool call's output to extract beliefs.
With ~48 successful tool calls × ~500-tokens-per-extractor-call, that's
~24k extra LLM tokens and several seconds of wall time per call. **Belief
auto-extraction is genuinely expensive** and should be opt-in for
production workloads, not default.

## Where Synapse's value actually lives

This run + the SDLC benchmark together paint the real picture:

| Pattern | Synapse value |
|---|---|
| **Hierarchical orchestrator + workers** (this test) | Mostly **observability**. Conflict prevention is redundant — the orchestrator already does it. |
| **Multi-orchestrator / parallel teams** (the SDLC benchmark planted this) | Real **safety**. Two engineering teams each touching `models/User.js` without knowing about each other → coherence 0.33 → 0.93 with auto_merge. |
| **Sub-agent spawning** (Hermes-style) | Real **safety**. Children don't know about each other. |
| **Same agent across many turns** (this test) | Synapse correctly does NOTHING (`agent_id != $new_agent` filter). Pure overhead would be a bug. |

## What I'd say to a skeptical reader

> "Your autonomous test found 0 conflicts. Doesn't that mean Synapse is useless?"

No — it means **Synapse's structural detection has a specific use case**:
multi-team, multi-orchestrator, or sub-agent-spawning scenarios where
agents independently target overlapping work. The autonomous test had
ONE orchestrator with global visibility, so it pre-deconflicted by
design.

The right claim for v0.2 is:
- "Synapse adds **observability** to any multi-agent stack" → confirmed
  (48 intentions, 124 beliefs cleanly captured here)
- "Synapse adds **safety** when agents lack a global coordinator" →
  confirmed by SDLC benchmark (0.33 → 0.93), NOT by this test
- "Synapse helps even with a competent orchestrator" → **disconfirmed
  by this test**. It runs cleanly but adds no detection value, only
  observability.

That's a more honest, narrower pitch than "Synapse improves coherence
2.8x" — which only holds in the multi-team scenario.

## What's in this directory

```
result.json                              — full run metadata
auto_<ts>_no_synapse.cast                — asciinema-style transcript (no_synapse mode)
auto_<ts>_no_synapse_timeline.json       — structured event timeline
auto_<ts>_no_synapse_snapshots.json      — filesystem state before/after each tool call
auto_<ts>_observer.cast                  — same for observer mode
auto_<ts>_observer_timeline.json
auto_<ts>_observer_snapshots.json
auto_<ts>_full.cast                      — same for full mode
auto_<ts>_full_timeline.json
auto_<ts>_full_snapshots.json
FINDINGS.md                              — this file
```

To replay any mode visually, drag the three files (`.cast`, `_timeline.json`,
`_snapshots.json`) into `ui/artifacts/replay-viewer.html`.

## What v0.3 should add

This test surfaced concrete v0.3 work:

1. **A multi-orchestrator benchmark** — the missing comparison case where
   Synapse's safety actually matters. Two LangGraph crews working on
   overlapping codebases, no shared coordinator. That's the scenario
   the SDLC benchmark proxies but should be tested for real.
2. **Belief extractor optimization** — 6.5x slowdown is too much for
   default-on. Options: only run extractor on file-write tools (not
   reads/searches), batch multiple calls into one prompt, use a smaller
   model.
3. **Belief-key clustering** — even with 124 beliefs persisted, zero
   divergences fired. Either the LLM picked unique keys per agent
   (likely) or the extractor isn't surfacing semantic overlap. Worth
   investigating with the captured timeline data.
