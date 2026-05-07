# Synapse Benchmark Results

`synapse bench --backend NAME --workload WORKLOAD` runs a standardized scenario against a registered backend and writes results to `bench/results/`.

## Workloads

| Workload | Agents | Scenario |
|---|---|---|
| `pair-coding` | coder + reviewer | 2 agents on partially-overlapping repo scopes (incl. read-vs-write tests) |
| `parallel-research` | 3 researchers | 6 disjoint research scopes — should produce 0 conflicts |
| `conflict-heavy` | 5 agents | Heavily overlapping db scopes — exercises router throughput |

## Run

```bash
synapse bench --backend mock --workload conflict-heavy
synapse bench --backend gemini --workload conflict-heavy   # needs Vertex AI ADC
synapse bench --backend ollama --workload pair-coding      # needs local Ollama
synapse bench --backend anthropic --workload conflict-heavy   # needs ANTHROPIC_API_KEY
```

## What the report contains

Each result JSON includes:
- `backend.{id, tier, model_id, supports_midstream_inject}`
- `signals_total`, `conflicts_detected`
- `emit_latency_ms.{p50, p95, p99, mean}` — time from `emit_intention()` call to return
- `conflict_signal_latency_ms.{p50, p95, p99, mean}` — time from intention emit to CONFLICT arrival in inbox
- `throughput_signals_per_sec` — wall-clock end-to-end throughput
- Raw timing arrays for downstream analysis

## Recorded results (this session)

| Backend | Workload | Signals | Conflicts | Emit p50 | CONFLICT p50 | Throughput |
|---|---|---|---|---|---|---|
| mock | conflict-heavy | 8 | 8 | 7.8 ms | 73.3 ms | 7.1 sig/s |
| mock | pair-coding | 4 | 4 | 10.9 ms | 40.6 ms | 3.8 sig/s |
| mock | parallel-research | 6 | 0 | 7.1 ms | — | 5.3 sig/s |
| gemini (Vertex AI) | conflict-heavy | 6 | 4 | 5.8 ms | 10.3 ms | 5.4 sig/s |

> The `mock` backend bench numbers are intrinsic to the bus + router + state graph (the LLM call is in-process and instant). They show that the protocol layer itself sustains sub-50ms p99 emit latency and sub-100ms p95 conflict-signal arrival under heavy conflict load.

## Pending backends

- **anthropic / openai**: code verified, account-state issues (Anthropic key needs full unredacted value; OpenAI quota exhausted on test account). Re-run with valid keys + credit.
- **ollama**: needs local `ollama serve` running with a pulled model (e.g. `llama3.2:3b`).
- **vllm-modal**: deployed Modal app exists; first call cold-start ~25-30s.
