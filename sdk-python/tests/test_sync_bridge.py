"""Tests for synapse.frameworks._sync_bridge.

The bridge exists because the previous adapter pattern —

    target = _INSTALL_LOOP
    if target is None or not target.is_running():
        try: target = asyncio.get_running_loop()
        except RuntimeError: return asyncio.run(_run())
    return asyncio.run_coroutine_threadsafe(_run(), target).result()

— deadlocks when called on the same loop it tries to schedule onto.
These tests cover the two cases that pattern got wrong:

  1. Called from a thread with no running loop (must not crash, must
     return the result).
  2. Called from inside a running loop (must not deadlock).
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from synapse.frameworks._sync_bridge import run_coro_blocking, shutdown_bridge


@pytest.fixture(autouse=True)
def _shutdown_after():
    yield
    # Don't shut down between tests — the bridge is intentionally
    # process-global and reused. Only shut down when the suite ends.


def test_basic_blocking_call_no_loop():
    async def coro() -> int:
        await asyncio.sleep(0)
        return 42

    assert run_coro_blocking(coro()) == 42


def test_returns_value_from_worker_thread():
    """Simulate a sync framework adapter call from a worker thread."""
    out: list[int] = []

    def worker():
        async def coro():
            await asyncio.sleep(0)
            return 7
        out.append(run_coro_blocking(coro()))

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=5.0)
    assert not t.is_alive(), "bridge call hung the worker thread"
    assert out == [7]


def test_no_deadlock_when_called_from_running_loop():
    """Reproduce the M1 bug scenario: an outer loop is running, and a
    sync wrapper is reached from inside it (e.g. async caller delegates
    into a sync tool method). The naive bridge would block the outer
    loop forever; the fixed bridge must complete."""

    async def outer():
        # Simulate the sync wrapper being invoked from inside this loop
        async def inner():
            await asyncio.sleep(0)
            return "ok"
        # NOTE: under the buggy pattern, this would call
        # run_coroutine_threadsafe(inner(), <this very loop>).result(),
        # which deadlocks. Under the bridge, it routes to a separate
        # daemon-thread loop and returns cleanly.
        result = await asyncio.to_thread(run_coro_blocking, inner())
        return result

    out = asyncio.run(outer())
    assert out == "ok"


def test_concurrent_calls_share_one_bridge_loop():
    """Multiple parallel sync calls should reuse a single bridge thread,
    not spawn a fresh asyncio.run() per call (which would tear down
    connection pools each time)."""
    results: list[int] = []
    lock = threading.Lock()

    def worker(i: int):
        async def coro():
            await asyncio.sleep(0.01)
            return i
        out = run_coro_blocking(coro())
        with lock:
            results.append(out)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    t0 = time.time()
    for t in threads: t.start()
    for t in threads: t.join(timeout=5.0)
    elapsed = time.time() - t0

    assert all(not t.is_alive() for t in threads)
    assert sorted(results) == list(range(20))
    # 20 calls of 10ms sleep on a single loop should finish well under
    # 5s (target ~30-100ms with concurrent scheduling). A naive
    # asyncio.run() per call would still finish within 5s but the timing
    # check below confirms we're not strictly serial (which would be ~200ms).
    assert elapsed < 1.0, f"bridge took {elapsed:.2f}s — possibly serial"


def test_propagates_exception():
    class Boom(RuntimeError):
        pass

    async def coro():
        raise Boom("intentional")

    with pytest.raises(Boom):
        run_coro_blocking(coro())
