"""`synapse bench` — standardized backend benchmark.

Workloads:
- pair-coding:        2 agents emit interleaved INTENTIONs on overlapping scopes
- parallel-research:  3 agents emit non-overlapping INTENTIONs (no conflicts)
- conflict-heavy:     5 agents emit on heavily overlapping scopes (most trigger
                      CONFLICT; tests router throughput)

Outputs JSON with: latency_p50/p95/p99, conflict_signal_latency_ms, signals_total,
conflicts_detected, est_cost_usd, throughput_signals_per_sec, plus the raw timings.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from synapse import Agent
from synapse.adapters import MockAdapter
from synapse.adapters.base import InferenceAdapter
from synapse.bus import Bus
from synapse.messages import MessageType
from synapse.state import StateGraph

REDIS_URL = os.getenv("SYNAPSE_REDIS_URL", "redis://localhost:6379/0")
POSTGRES_DSN = os.getenv(
    "SYNAPSE_POSTGRES_DSN",
    "postgresql://synapse:synapse_dev@localhost:5432/synapse",
)


# ---------------------------------------------------------------------------
# Backend factory
# ---------------------------------------------------------------------------
def _build_backend(name: str) -> InferenceAdapter:
    if name == "mock":
        return MockAdapter(scripted_response="ok", delay_per_token_ms=0)
    if name == "anthropic":
        from synapse.adapters.hosted import AnthropicAdapter
        return AnthropicAdapter(model="claude-haiku-4-5-20251001", max_tokens=64)
    if name == "gemini":
        from synapse.adapters.hosted import GeminiAdapter
        return GeminiAdapter(
            model="gemini-2.5-flash",
            max_tokens=64,
            project=os.environ.get("SYNAPSE_GCP_PROJECT"),
        )
    if name == "openai":
        from synapse.adapters.hosted import OpenAIAdapter
        return OpenAIAdapter(model="gpt-4o-mini", max_tokens=64)
    if name == "ollama":
        from synapse.adapters.local import OllamaAdapter
        return OllamaAdapter(model="llama3.2:3b", max_tokens=64)
    if name == "vllm-modal":
        from synapse.adapters.native import VLLMModalAdapter
        return VLLMModalAdapter(max_tokens=64)
    raise ValueError(f"unknown backend: {name}")


# ---------------------------------------------------------------------------
# Workload definitions
# ---------------------------------------------------------------------------
WORKLOADS: dict[str, dict[str, Any]] = {
    "pair-coding": {
        "agents": ["coder", "reviewer"],
        "scopes": [
            ["repo.auth.middleware:w"],
            ["repo.auth.middleware:w"],   # overlaps -> CONFLICT
            ["repo.auth.tests:w"],
            ["repo.auth.tests:r"],         # read; no conflict
        ],
    },
    "parallel-research": {
        "agents": ["researcher_a", "researcher_b", "researcher_c"],
        "scopes": [
            ["research.papers.security:r"],
            ["research.papers.crypto:r"],
            ["research.papers.networking:r"],
            ["research.summary.security:w"],
            ["research.summary.crypto:w"],
            ["research.summary.networking:w"],
        ],
    },
    "conflict-heavy": {
        "agents": ["a1", "a2", "a3", "a4", "a5"],
        "scopes": [
            ["db.users.schema:w"],
            ["db.users.schema:w"],
            ["db.users.schema:w"],
            ["db.users.email:w"],
            ["db.users.**:w"],
            ["db.users.email:w"],
            ["db.posts.schema:w"],
            ["db.posts.schema:w"],
        ],
    },
}


# ---------------------------------------------------------------------------
async def _wait_ready(name: str, fn: Callable[[], Any], retries: int = 30) -> None:
    for _ in range(retries):
        try:
            await fn()
            return
        except Exception:
            await asyncio.sleep(1)
    raise RuntimeError(f"{name} not ready")


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


# ---------------------------------------------------------------------------
async def run_bench(
    backend: str,
    workload: str,
    output_dir: str = "bench/results",
    max_signals: int = 10,
) -> int:
    if workload not in WORKLOADS:
        print(f"unknown workload: {workload}", file=sys.stderr)
        return 1

    print(f"\nsynapse bench  backend={backend}  workload={workload}")
    print("=" * 60)

    # Build backend (validates capabilities + key availability)
    try:
        sample_backend = _build_backend(backend)
    except Exception as e:
        print(f"FAIL: cannot build backend {backend!r}: {e}")
        return 2
    caps = sample_backend.capabilities

    # Bus + state
    from runtime.router.worker import Router
    bus = Bus(REDIS_URL)
    state = StateGraph(POSTGRES_DSN)
    await _wait_ready("redis", bus.connect)
    await _wait_ready("postgres", state.connect)

    session_id = f"bench_{backend}_{workload}_{uuid.uuid4().hex[:6]}"

    # Agents
    spec = WORKLOADS[workload]
    agents: dict[str, Agent] = {}
    for aid in spec["agents"]:
        agents[aid] = Agent(
            id=aid,
            session=session_id,
            backend=_build_backend(backend),
            subscribes=["**"],
            bus=bus,
            state=state,
        )

    # Router (in-process)
    router = Router(bus, state, session_id, consumer="bench_router")
    router_task = asyncio.create_task(router.run())

    # Track per-intention timings; conflict_signal_latency = time from
    # intention emit to CONFLICT received in inbox
    intention_emit_times: dict[str, float] = {}
    conflict_arrival_times: dict[str, float] = {}

    # Spawn an inbox watcher per agent that records when CONFLICT arrives
    async def watch_inbox(agent: Agent) -> None:
        while True:
            await asyncio.sleep(0.01)
            try:
                envs = await bus.drain_inbox(agent.id, last_id=agent._inbox_cursor)  # type: ignore[attr-defined]
                for entry_id, env in envs:
                    agent._inbox_cursor = entry_id  # type: ignore[attr-defined]
                    if env.type == MessageType.CONFLICT:
                        target = env.payload.get("intention_id")
                        if target and target not in conflict_arrival_times:
                            conflict_arrival_times[target] = time.time()
            except Exception:
                pass

    try:
        from contextlib import AsyncExitStack
        async with AsyncExitStack() as stack:
            for a in agents.values():
                await stack.enter_async_context(a.lifecycle())

            # Start inbox watchers
            watchers = [asyncio.create_task(watch_inbox(a)) for a in agents.values()]

            # Drive the workload — round-robin assign scopes to agents
            agent_list = list(agents.values())
            scopes = spec["scopes"][:max_signals]
            emit_latencies_ms: list[float] = []
            t0 = time.time()

            for i, scope in enumerate(scopes):
                agent = agent_list[i % len(agent_list)]
                start = time.time()
                int_id, _ = await agent.emit_intention(
                    action={"tool": "noop", "args": {}},
                    scope=scope,
                    expected_outcome=f"bench step {i}",
                    blocking=False,
                )
                elapsed_ms = (time.time() - start) * 1000
                emit_latencies_ms.append(elapsed_ms)
                intention_emit_times[int_id] = start

            # Give the router 1s to flush all conflict signals
            await asyncio.sleep(1.0)
            t1 = time.time()

            # Stop watchers
            for w in watchers:
                w.cancel()

            # Compute conflict-signal latencies
            conflict_latencies_ms: list[float] = []
            for int_id, t_emit in intention_emit_times.items():
                t_arr = conflict_arrival_times.get(int_id)
                if t_arr is not None:
                    conflict_latencies_ms.append((t_arr - t_emit) * 1000)

            wall_seconds = max(0.001, t1 - t0)
            results = {
                "backend": {
                    "id": caps.backend_id,
                    "tier": caps.tier,
                    "model_id": caps.model_id,
                    "supports_midstream_inject": caps.supports_midstream_inject,
                    "avg_overhead_per_signal": caps.avg_overhead_per_signal,
                    "is_reasoning_model": caps.is_reasoning_model,
                },
                "workload": workload,
                "session_id": session_id,
                "signals_total": len(emit_latencies_ms),
                "conflicts_detected": len(conflict_latencies_ms),
                "emit_latency_ms": {
                    "p50": _percentile(emit_latencies_ms, 50),
                    "p95": _percentile(emit_latencies_ms, 95),
                    "p99": _percentile(emit_latencies_ms, 99),
                    "mean": statistics.fmean(emit_latencies_ms) if emit_latencies_ms else 0,
                },
                "conflict_signal_latency_ms": {
                    "p50": _percentile(conflict_latencies_ms, 50),
                    "p95": _percentile(conflict_latencies_ms, 95),
                    "p99": _percentile(conflict_latencies_ms, 99),
                    "mean": (
                        statistics.fmean(conflict_latencies_ms)
                        if conflict_latencies_ms
                        else 0
                    ),
                } if conflict_latencies_ms else None,
                "throughput_signals_per_sec": len(emit_latencies_ms) / wall_seconds,
                "wall_seconds": wall_seconds,
                "raw_emit_latencies_ms": emit_latencies_ms,
                "raw_conflict_latencies_ms": conflict_latencies_ms,
            }

            # Pretty-print
            print(f"  signals total:           {results['signals_total']}")
            print(f"  conflicts detected:      {results['conflicts_detected']}")
            print(f"  emit p50 / p95 / p99:    "
                  f"{results['emit_latency_ms']['p50']:.1f} / "
                  f"{results['emit_latency_ms']['p95']:.1f} / "
                  f"{results['emit_latency_ms']['p99']:.1f} ms")
            if results["conflict_signal_latency_ms"]:
                cl = results["conflict_signal_latency_ms"]
                print(f"  CONFLICT p50 / p95:      "
                      f"{cl['p50']:.1f} / {cl['p95']:.1f} ms")
            print(f"  throughput:              "
                  f"{results['throughput_signals_per_sec']:.1f} signals/s")
            print(f"  wall:                    {results['wall_seconds']:.3f}s")

            # Write to disk
            out_dir = Path(output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d-%H%M%S")
            out_path = out_dir / f"{backend}_{workload}_{ts}.json"
            out_path.write_text(json.dumps(results, indent=2))
            print(f"\n  results -> {out_path}")
            return 0
    finally:
        router.stop()
        try:
            await asyncio.wait_for(router_task, timeout=2)
        except asyncio.TimeoutError:
            router_task.cancel()
        await bus.close()
        await state.close()
