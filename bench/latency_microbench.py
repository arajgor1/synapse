"""Latency micro-benchmark for ``synapse.intend()``.

Measures wrapper overhead on three paths:

  * **no-conflict**: single agent, no other claimants on the scope.
    The dominant code path for production workloads.
  * **gate-pass**: another agent JUST resolved on the same scope, so
    the immediate state lookup finds nothing active. Should be on the
    fast path.
  * **gate-then-conflict**: another agent currently holds an active
    intention on the scope. Gate window observes a CONFLICT.

We run each path N times back-to-back and report median + p95 + p99.
Outputs JSON to ``bench/results/latency_<ts>.json`` and a plaintext
table to stdout.

Run:

    python bench/latency_microbench.py [--iterations 100] [--mode zero-infra|live]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

# Allow running from repo root before pip-install.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk-python"))

import synapse


def _stats(samples: list[float]) -> dict:
    """Convert a list of seconds to a dict of millisecond stats."""
    if not samples:
        return {"n": 0, "min_ms": 0, "median_ms": 0, "p95_ms": 0, "p99_ms": 0, "max_ms": 0}
    ms = sorted(s * 1000 for s in samples)
    return {
        "n": len(ms),
        "min_ms": round(ms[0], 3),
        "median_ms": round(statistics.median(ms), 3),
        "p95_ms": round(ms[int(len(ms) * 0.95)] if len(ms) > 1 else ms[0], 3),
        "p99_ms": round(ms[int(len(ms) * 0.99)] if len(ms) > 1 else ms[0], 3),
        "max_ms": round(ms[-1], 3),
    }


async def _measure_no_conflict(iterations: int) -> list[float]:
    """Single agent, distinct scopes, ONE session (realistic — most user
    workloads run within a single session for a long time). Each call's
    scope is unique so prior intents don't surface as conflicts."""
    samples: list[float] = []
    sess = "bench_no_conflict_session"
    for i in range(iterations):
        scope = [f"bench.no_conflict.iter_{i}:w"]
        t0 = time.perf_counter()
        async with synapse.intend(
            scope=scope, agent="bench_runner", session=sess,
            expected_outcome="bench",
            blocking=True, gate_ms=50,
        ):
            pass
        samples.append(time.perf_counter() - t0)
    return samples


async def _measure_gate_pass(iterations: int) -> list[float]:
    """Another agent JUST resolved on the scope. Fast path should kick in."""
    samples: list[float] = []
    sess = "bench_gate_pass_session"
    for i in range(iterations):
        scope = [f"bench.gate_pass.iter_{i}:w"]
        # First agent claims and resolves, then second agent claims.
        async with synapse.intend(
            scope=scope, agent="other_agent", session=sess,
            blocking=False,
        ):
            pass
        # Now measure the second claim — overlap is "recent_resolution",
        # not active. With the active-only fast path, this should be quick.
        t0 = time.perf_counter()
        async with synapse.intend(
            scope=scope, agent="bench_runner", session=sess,
            blocking=True, gate_ms=50,
        ):
            pass
        samples.append(time.perf_counter() - t0)
    return samples


async def _measure_gate_then_conflict(iterations: int) -> list[float]:
    """Another agent CURRENTLY holds the scope active. Gate window will
    observe a CONFLICT before the body runs."""
    samples: list[float] = []
    sess = "bench_gate_conflict_session"
    for i in range(iterations):
        scope = [f"bench.gate_conflict.iter_{i}:w"]

        async def hold_scope():
            async with synapse.intend(
                scope=scope, agent="other_agent", session=sess,
                blocking=False,
            ):
                await asyncio.sleep(0.05)

        async def claim_and_measure():
            await asyncio.sleep(0.005)
            t0 = time.perf_counter()
            async with synapse.intend(
                scope=scope, agent="bench_runner", session=sess,
                blocking=True, gate_ms=50,
            ):
                pass
            return time.perf_counter() - t0

        _, dt = await asyncio.gather(hold_scope(), claim_and_measure())
        samples.append(dt)
    return samples


async def _warmup() -> None:
    """One unmeasured call to amortise lazy connect cost out of the
    benchmark — first call sets up bus, state pool, agent register, and
    starts the in-process router for the session."""
    async with synapse.intend(
        scope=["bench.warmup:w"], agent="bench_warmer",
        session="bench_warmup", blocking=False,
    ):
        pass


async def main(iterations: int, mode_label: str) -> None:
    print(f"\nsynapse latency micro-benchmark")
    print(f"  iterations per scenario : {iterations}")
    print(f"  mode                    : {mode_label}")
    print(f"  synapse version         : {synapse.__version__}")

    await _warmup()

    no_conflict = await _measure_no_conflict(iterations)
    gate_pass = await _measure_gate_pass(iterations)
    gate_conflict = await _measure_gate_then_conflict(iterations)

    results = {
        "synapse_version": synapse.__version__,
        "mode": mode_label,
        "iterations": iterations,
        "no_conflict": _stats(no_conflict),
        "gate_pass":   _stats(gate_pass),
        "gate_then_conflict": _stats(gate_conflict),
    }

    print("\n  scenario              n     median    p95     p99     max")
    print("  " + "-" * 56)
    for name in ("no_conflict", "gate_pass", "gate_then_conflict"):
        s = results[name]
        print(
            f"  {name:<20} {s['n']:>4}  "
            f"{s['median_ms']:>7.2f}ms {s['p95_ms']:>6.2f}ms "
            f"{s['p99_ms']:>6.2f}ms {s['max_ms']:>6.2f}ms"
        )

    out_dir = Path(__file__).resolve().parent / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"latency_{mode_label}_{int(time.time())}.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n  wrote {out_path}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--iterations", type=int, default=50)
    p.add_argument(
        "--mode", default="zero-infra",
        choices=["zero-infra", "live"],
        help="Backend mode. zero-infra = in-memory bus + sqlite; "
             "live = requires SYNAPSE_REDIS_URL + SYNAPSE_POSTGRES_DSN set.",
    )
    args = p.parse_args()
    if args.mode == "zero-infra":
        os.environ.pop("SYNAPSE_REDIS_URL", None)
        os.environ.pop("SYNAPSE_POSTGRES_DSN", None)
    asyncio.run(main(args.iterations, args.mode))
