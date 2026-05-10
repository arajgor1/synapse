"""W3.1 — synthetic soak test for ``synapse.intend()``.

Goal: prove Synapse's hot loop is leak-free + survives long runs without
exhausting connection pools / memory / file descriptors. Drives N
intentions per second across M agents on K rotating scopes for D minutes.

What we measure
---------------
* RSS growth over time (must be bounded; <50MB growth target)
* Intentions/second sustained throughput
* p50 + p95 latency per emit
* Number of "Connection refused" / "operation in progress" errors
* SQLite file size growth

Default workload (zero-infra):
  * 100,000 emits across 50 unique scopes by 5 agents over 10 minutes
  * Resolves each immediately so the active set stays bounded
  * Logs RSS every 10s

Run:

    python bench/soak_test.py [--duration 600] [--agents 5] [--scopes 50] [--rps 100]

Outputs JSON to ``bench/results/soak_<ts>.json``.
"""
from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk-python"))

import synapse


def _rss_mb() -> float:
    """Return current RSS in MB. Uses psutil if available, else /proc.
    Returns 0.0 on platforms with neither (Windows fallback below)."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except ImportError:
        pass
    try:
        # Linux fallback
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1])
                    return kb / 1024
    except FileNotFoundError:
        pass
    # Windows fallback via ctypes
    try:
        import ctypes
        from ctypes.wintypes import DWORD, HANDLE
        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", DWORD), ("PageFaultCount", DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]
        kernel32 = ctypes.WinDLL("kernel32")
        psapi = ctypes.WinDLL("psapi")
        h = kernel32.GetCurrentProcess()
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        psapi.GetProcessMemoryInfo(HANDLE(h), ctypes.byref(counters), counters.cb)
        return counters.WorkingSetSize / (1024 * 1024)
    except Exception:
        return 0.0


async def _emit_one(agent: str, session: str, scope: list[str]) -> tuple[float, bool]:
    """Single intend() call. Returns (latency_seconds, success)."""
    t0 = time.perf_counter()
    try:
        async with synapse.intend(
            scope=scope, agent=agent, session=session,
            blocking=True, gate_ms=20,
        ):
            pass
        return (time.perf_counter() - t0, True)
    except Exception:
        return (time.perf_counter() - t0, False)


async def main(args: argparse.Namespace) -> None:
    print(f"\nsynapse soak test")
    print(f"  duration   : {args.duration}s")
    print(f"  agents     : {args.agents}")
    print(f"  scopes     : {args.scopes}")
    print(f"  target rps : {args.rps}")
    print(f"  synapse    : v{synapse.__version__}")

    sqlite_path = Path(os.environ.get("SYNAPSE_SQLITE_PATH", "/tmp/soak.db"))
    if sqlite_path.exists():
        sqlite_path.unlink()
    os.environ["SYNAPSE_SQLITE_PATH"] = str(sqlite_path)

    # Warmup
    async with synapse.intend(
        scope=["soak.warmup:w"], agent="warmup", session="soak_warmup",
        blocking=False,
    ):
        pass

    rss_baseline = _rss_mb()
    print(f"  rss base   : {rss_baseline:.1f} MB\n")

    started = time.monotonic()
    deadline = started + args.duration
    next_log = started + 10.0

    samples: list[float] = []
    rss_over_time: list[tuple[float, float]] = [(0.0, rss_baseline)]
    n_calls = 0
    n_failures = 0
    next_call = started

    interval = 1.0 / args.rps
    session = "soak_session"
    agents = [f"soak_agent_{i}" for i in range(args.agents)]
    scopes = [[f"soak.scope_{i}:w"] for i in range(args.scopes)]

    while time.monotonic() < deadline:
        # Fire one emit, paced to target rps.
        agent = agents[n_calls % args.agents]
        scope = scopes[n_calls % args.scopes]
        latency, ok = await _emit_one(agent, session, scope)
        n_calls += 1
        if ok:
            samples.append(latency)
        else:
            n_failures += 1

        # Pace
        next_call += interval
        sleep_for = next_call - time.monotonic()
        if sleep_for > 0:
            await asyncio.sleep(sleep_for)

        # Periodic memory log
        if time.monotonic() >= next_log:
            elapsed = time.monotonic() - started
            rss = _rss_mb()
            rss_over_time.append((round(elapsed, 1), round(rss, 1)))
            actual_rps = n_calls / elapsed
            sqlite_mb = sqlite_path.stat().st_size / (1024 * 1024) if sqlite_path.exists() else 0
            print(
                f"  t={elapsed:>5.0f}s  rss={rss:>6.1f}MB  "
                f"calls={n_calls:>6}  rps={actual_rps:>5.1f}  "
                f"fails={n_failures:>3}  sqlite={sqlite_mb:>5.1f}MB"
            )
            next_log = time.monotonic() + 10.0

    elapsed = time.monotonic() - started
    rss_final = _rss_mb()
    rss_growth = rss_final - rss_baseline
    sqlite_mb = sqlite_path.stat().st_size / (1024 * 1024) if sqlite_path.exists() else 0

    ms = sorted(s * 1000 for s in samples)

    summary = {
        "synapse_version": synapse.__version__,
        "duration_s": round(elapsed, 1),
        "agents": args.agents,
        "scopes": args.scopes,
        "target_rps": args.rps,
        "actual_rps": round(n_calls / elapsed, 1),
        "n_calls": n_calls,
        "n_failures": n_failures,
        "failure_rate": round(n_failures / max(n_calls, 1), 4),
        "rss_baseline_mb": round(rss_baseline, 1),
        "rss_final_mb": round(rss_final, 1),
        "rss_growth_mb": round(rss_growth, 1),
        "sqlite_size_mb": round(sqlite_mb, 1),
        "latency_median_ms": round(statistics.median(ms), 3) if ms else None,
        "latency_p95_ms": round(ms[int(len(ms) * 0.95)], 3) if ms else None,
        "latency_p99_ms": round(ms[int(len(ms) * 0.99)], 3) if ms else None,
        "latency_max_ms": round(ms[-1], 3) if ms else None,
        "rss_over_time": rss_over_time,
    }

    print(f"\n=== SOAK SUMMARY ===")
    print(f"  duration         : {summary['duration_s']}s")
    print(f"  total calls      : {summary['n_calls']}")
    print(f"  actual rps       : {summary['actual_rps']}")
    print(f"  failure rate     : {summary['failure_rate']:.2%}")
    print(f"  RSS baseline     : {summary['rss_baseline_mb']:.1f} MB")
    print(f"  RSS final        : {summary['rss_final_mb']:.1f} MB")
    print(f"  RSS growth       : {summary['rss_growth_mb']:.1f} MB")
    print(f"  SQLite size      : {summary['sqlite_size_mb']:.1f} MB")
    print(f"  latency p50/p95/p99/max ms: "
          f"{summary['latency_median_ms']} / {summary['latency_p95_ms']} / "
          f"{summary['latency_p99_ms']} / {summary['latency_max_ms']}")

    out = Path(__file__).resolve().parent / "results" / f"soak_{int(time.time())}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n  wrote {out}")

    # Pass/fail criteria
    passed = (
        summary["failure_rate"] < 0.01
        and summary["rss_growth_mb"] < 50
        and (summary["latency_p95_ms"] or 0) < 100
    )
    print(f"\n  RESULT: {'PASS' if passed else 'FAIL'}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--duration", type=int, default=300, help="Run duration in seconds (default 300)")
    p.add_argument("--agents", type=int, default=5)
    p.add_argument("--scopes", type=int, default=50)
    p.add_argument("--rps", type=int, default=100)
    args = p.parse_args()
    asyncio.run(main(args))
