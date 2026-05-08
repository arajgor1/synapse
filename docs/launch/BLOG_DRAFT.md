# Synapse: the safety layer for multi-agent AI systems

*v0.2.1-alpha — open-source under Apache 2.0. Audit existing logs, prevent collisions live, and resolve them with your own LLM.*

---

## What this post is

I built [Synapse](https://github.com/arajgor1/synapse) — an open-source protocol + libraries that detect, audit, and resolve agent collisions. This post explains:

- What problem Synapse solves (and where it doesn't)
- The two benchmarks that ground every claim
- An honest finding that *disconfirmed* my early pitch and forced me to narrow it
- How to try it on your own data in under a minute

No SaaS pitch. Self-hosted by design. **Bring your own LLM** — Synapse never charges your account without explicit consent.

---

## The problem

When AI agents share state — same repo, same database, same customer — they collide. The autonomous AI agents you're shipping today already step on each other in ways your observability tools don't surface.

Three concrete cases I've measured live:

1. **The silent overwrite.** Two coding agents both rewrite `models/User.js`. The last one wins. The first one's contribution — say, the `bio` and `avatar_url` fields — is gone. Nobody notices until production.
2. **The stale-base.** Agent A finishes a write at T=5s. Agent B starts a related write at T=15s, never having seen A's version. B clobbers A. The intentions never overlapped in time, but the result is corrupted.
3. **The semantic divergence.** Three data agents each compute `revenue` differently — `qty*price` vs `qty*price*(1-discount)` vs `qty*price - returns`. They write to different files (no scope overlap). The downstream report has three contradictory totals.

LangSmith / Phoenix / Langfuse will *log* all three of these. None of them will *prevent* any of them.

---

## What Synapse does

Three layers, designed to fit into the funnel:

### Layer 1: `synapse audit` — see what you've already missed

```bash
pip install synapse-protocol
synapse audit ./your-langsmith-export.json
```

```
Found 23 silent conflicts across 8 sessions.
Estimated waste: ~15.4k tokens / ~$0.31.
Full report: ./synapse-audit-2026-05-08.html
```

No infrastructure. No live integration. Just point it at OpenInference OTel JSON, LangSmith export JSON, or generic JSONL — Synapse reads what you already have and produces an HTML report.

### Layer 2: `synapse-protocol` — the open standard + library

```bash
pip install 'synapse-protocol[live]'
```

```python
import synapse
async with synapse.intend(scope=["repo.fs.user.py:w"], agent="reviewer") as i:
    if i.has_conflicts:
        await i.pivot()
    result = await my_tool_call()
```

A single envelope protocol (frozen at v1.0) backed by Python and TypeScript SDKs. **11 framework adapters** across both ecosystems: LangGraph, CrewAI, AutoGen, OpenAI Agents SDK, Pydantic AI, smolagents, Vercel AI SDK, LangGraph.js, Hermes, Paperclip, OpenClaw.

### Layer 3: safety policies — fix what audit detected

```python
synapse.install(
    framework="langgraph",
    merge_policy=synapse.MergePolicy.auto_merge,    # LLM-mediated reconciliation
    critical_scopes=["billing.*", "prod.deploy.*"], # hard-block on these
    emit_beliefs_from_tool_results=True,             # catch semantic conflicts
)
```

When CONFLICT fires:
- `redirect` (default) — log + continue
- `wait` — block briefly + retry
- `abort` — fail with a clean `SynapseConflict` exception
- **`auto_merge`** — call your BYO-LLM with both versions, use the merged result

Plus `critical_scopes` for hard-blocks on production-sensitive paths, and BELIEF auto-extraction for the semantic-conflict case.

---

## The headline benchmark

I built a realistic 6-agent SDLC workflow — the kind of thing real teams use AI agents for: build a multi-tenant SaaS billing platform (mini-Stripe). Six agents (PM / Architect / Backend / Integrations / Frontend / QA / DevOps), 25 file artifacts, real Anthropic Haiku calls, real Postgres state graph, real Redis bus, no scripted oracle.

Same workload, three modes:

| Mode | Coherence | Conflicts caught | Auto-merges | Wall clock |
|---|---|---|---|---|
| `no_synapse` (fire and forget) | **0.33** | 0 | 0 | 65s |
| `with_synapse_redirect` (warn-only) | 0.33 | 9 | 0 | 73s |
| **`with_synapse_full` (auto_merge + beliefs)** | **0.93** ✓ | 18 | 9 | 122s |

**Coherence** = the fraction of each agent's planted contribution that survived in the final files. Without Synapse, only one third of the team's intended contributions made it through (last writer wins). With full Synapse, 93% — every engineer's fields, decorators, and tests survived because the LLM-mediated auto-merge reconciled their conflicting drafts.

**2.8x coherence improvement.** Same agents, same prompts, same model. The only difference is whether Synapse is active.

---

## The benchmark that disconfirmed my early pitch

I'd been telling people Synapse helps "any multi-agent system." Then I ran an autonomous test where a real LangGraph orchestrator decided what each of 4 worker agents should build, turn by turn, with full visibility into what had been done so far.

| Mode | Files | Cross-agent collisions | Synapse caught |
|---|---|---|---|
| `no_synapse` | 34 | 1 | n/a (not installed) |
| `observer` (Synapse watches, never blocks) | 27 | **0** | **0** |
| `full` (auto_merge + beliefs) | 26 | **0** | **0** |

**Synapse caught zero conflicts in observer + full modes — not because it broke, but because the orchestrator pre-deconflicted everything.** Each agent owned their files (auth → backend, Stripe → integrations, UI → frontend, tests → QA). They never overlapped. There was nothing to detect.

That's a problem for the "any multi-agent system" pitch. The honest narrowing:

| Pattern | Synapse value |
|---|---|
| Multi-team / multi-orchestrator sharing a codebase | ✅ **Real safety.** This is the SDLC-benchmark case. |
| Sub-agent spawning (Hermes / swarm patterns) | ✅ **Real safety.** Children don't know about each other. |
| Audit existing trace data | ✅ **Real audit.** Works on any framework's exports. |
| Hierarchical orchestrator + workers (LangGraph supervisor, CrewAI hierarchy) | ⚠️ **Mostly observability.** Synapse runs cleanly but the orchestrator already coordinates. |
| Single agent | ❌ **Pure overhead.** Don't install. |

The full write-up + capture artifacts are in [`bench/results/v02_autonomous_*/FINDINGS.md`](https://github.com/arajgor1/synapse/blob/main/bench/results/) — the run produced asciinema-style transcripts, structured event timelines, and filesystem snapshots that you can replay with the included viewer.

---

## How Synapse fits with the tools you already use

Synapse is **complementary**, not competitive:

| Layer | Standard | What it solves |
|---|---|---|
| Tool access | [MCP](https://modelcontextprotocol.io) | agents ↔ tools |
| Cross-vendor agent comms | [A2A](https://github.com/a2aproject/A2A) | agent ↔ agent across vendors |
| Commerce | ACP / UCP | agent payments |
| Observability | LangSmith / Phoenix / Langfuse | tracing + eval |
| **Coordination + safety** | **Synapse** | "who writes what when 3 agents share state" |

Use LangSmith for traces. Use Synapse to catch the collisions LangSmith logs but doesn't prevent. They sit on top of each other.

---

## Bring your own LLM

Synapse never makes a paid LLM call without explicit caller consent:

```python
synapse.set_llm(synapse.from_anthropic(your_anthropic_client))
# or
synapse.set_llm(synapse.from_openai(your_openai_client))
# or
synapse.set_llm(synapse.from_vercel_ai(your_vercel_model))
# or local Ollama, or LangChain bridge, or anything else
```

If you don't call `set_llm()`, the LLM-mediated paths (auto_merge, BELIEF divergence detection) become no-ops with clear log messages. The structural detection (scope overlap, stale-base overwrite, critical scopes) still works. **Zero surprise charges, zero vendor lock-in.**

---

## The gaps I'd flag honestly

Things I'm not hiding:

1. **`emit_beliefs_from_tool_results=True` is expensive.** It runs the BYO-LLM on every successful tool call to extract beliefs. The autonomous benchmark showed it 6.5x slower than no_synapse mode. Recommended for high-value workflows only, not as a default.
2. **BELIEF-key clustering is missing.** Two agents can pick `revenue_formula` vs `revenue_calc` for the same fact. Synapse currently treats them as different keys. v0.3 work.
3. **Hierarchical orchestrator pattern adds little.** Synapse runs cleanly but the orchestrator pre-deconflicts. If your stack is purely orchestrator + workers, audit-only is the right install.
4. **Multi-orchestrator benchmark not yet done.** SDLC benchmark proxies it, but a true two-team-no-shared-coordinator test is v0.3 work.

---

## Try it

```bash
# Audit your existing trace data, no infrastructure needed
pip install synapse-protocol
synapse audit ./your-langsmith-export.json

# Or wire it in live with full safety semantics
pip install 'synapse-protocol[live]'
synapse up
```

- Repo: [github.com/arajgor1/synapse](https://github.com/arajgor1/synapse)
- Spec: [`spec/protocol-v1.0/`](https://github.com/arajgor1/synapse/tree/main/spec/protocol-v1.0)
- Benchmarks: [`bench/benchmarks.md`](https://github.com/arajgor1/synapse/blob/main/bench/benchmarks.md)
- Issues: [github.com/arajgor1/synapse/issues](https://github.com/arajgor1/synapse/issues)

Open-source. Apache 2.0. No SaaS. Self-hosted by design.

---

*v0.2.1-alpha · Aadit Rajgor*
