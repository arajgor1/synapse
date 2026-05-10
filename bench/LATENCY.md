# Synapse latency micro-benchmark

**TL;DR — Synapse adds ~1.6ms median (~2.6ms p95) per write tool call on the no-conflict path in zero-infra mode.** That's well under the latency budget any LLM-driven workload can absorb (single LLM token ≈ 30-100ms).

## Methodology

`bench/latency_microbench.py` measures `synapse.intend()` overhead end-to-end across three scenarios:

| Scenario | What it measures |
|---|---|
| `no_conflict` | Single agent emits intentions on distinct scopes within one session — the dominant production path |
| `gate_pass`   | Another agent JUST resolved on the same scope — fast path detects no active conflict, skips the gate window |
| `gate_then_conflict` | Another agent CURRENTLY holds the scope active — fast-path immediate self-check finds the conflict, returns synthesized Conflict envelope without waiting the full gate window |

Run with:

```bash
python bench/latency_microbench.py --iterations 50 --mode zero-infra
```

## Results — zero-infra mode (in-memory bus + SQLite)

`synapse-protocol-0.2.2a4`, Windows 11 + Python 3.12, 50 iterations per scenario:

| Scenario | n | median | p95 | p99 | max |
|---|---|---|---|---|---|
| `no_conflict` | 50 | **1.59ms** | 2.62ms | 14.49ms | 14.49ms |
| `gate_pass` | 50 | **2.86ms** | 4.06ms | 16.15ms | 16.15ms |
| `gate_then_conflict` | 50 | **3.32ms** | 5.37ms | 15.22ms | 15.22ms |

## What changed in v0.2.2a4 — active-scope fast path

Before v0.2.2a4: `synapse.intend(blocking=True, gate_ms=50)` always waited the full `gate_ms` for CONFLICT envelopes via the agent's inbox, even when no other agent currently held the scope. Median no-conflict latency was **~80ms** at default gate.

After v0.2.2a4: `Agent.emit_intention` does an immediate `find_conflicts` query against the state graph right after persisting our intention. The result is authoritative because:

1. Our row is already in the state graph, so we filter it out via `id != ours`.
2. Any concurrent writer who committed before our query sees a `now()`-ordered row — visible to us.

If the immediate check returns empty, we skip the gate window entirely. If it finds a conflict, we synthesize a `Conflict` envelope from the row(s) and briefly check the inbox for a router-enriched version (which may carry resolution-tier hints).

**Net effect: 50x latency reduction on the dominant production path** with zero loss of correctness in single-process mode and identical conflict-detection accuracy in multi-process mode (the router still consumes our INTENT envelope and emits CONFLICTs to *other* agents whose intents arrive after ours).

## Comparison points

- Anthropic Haiku 4.5 single-token decode: ~30-100ms. Synapse overhead is ~5% of the cheapest LLM step.
- Postgres single-row INSERT (typical local): ~1-3ms. Synapse zero-infra emit is on par.
- Redis xadd (typical local): ~0.2-1ms. Synapse zero-infra emit is heavier because it does a state INSERT + bus publish + self-check find_conflicts (3 ops vs 1).

## Live mode (Redis + Postgres)

To measure live mode, run the in-image setup from `runtime/modal/framework_sandbox.py` or set up Redis + Postgres locally and:

```bash
SYNAPSE_REDIS_URL=redis://localhost:6379/0 \
SYNAPSE_POSTGRES_DSN=postgresql://synapse:synapse_dev@localhost:5432/synapse \
python bench/latency_microbench.py --iterations 50 --mode live
```

Expected: 5-15ms median for `no_conflict` (Postgres + Redis network round trips dominate).

## Reproduction

```
git clone https://github.com/arajgor1/synapse
cd synapse
pip install -e ./sdk-python
python bench/latency_microbench.py --iterations 100
```

JSON results are saved to `bench/results/latency_<mode>_<timestamp>.json`.
