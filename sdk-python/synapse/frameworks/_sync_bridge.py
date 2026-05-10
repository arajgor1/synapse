"""Sync-to-async bridge for framework adapters.

Many sync framework dispatch methods (LangChain ``BaseTool.invoke``,
LlamaIndex ``FunctionTool.call``, CrewAI ``Task.execute_sync``, etc.) need
to run an ``async with intend(...)`` block inside Synapse coordination.

The naive bridge —

    target = _INSTALL_LOOP
    if target is None or not target.is_running():
        try: target = asyncio.get_running_loop()
        except RuntimeError: return asyncio.run(_run())
    return asyncio.run_coroutine_threadsafe(_run(), target).result()

— deadlocks if the wrapper is invoked **on** the loop it tries to schedule
onto: ``run_coroutine_threadsafe(...).result()`` blocks the calling thread
waiting for the coroutine, but the only thread that can advance the
coroutine IS the calling thread. (LangChain ``invoke`` is documented as
sync, but agents frequently call it inside an outer ``asyncio.run`` or
from within an async tool implementation that delegates back through
``invoke`` — both legal and both fatal under the naive bridge.)

This module fixes that by maintaining a **dedicated background event
loop in its own daemon thread**. Sync wrappers schedule onto that loop
via ``run_coroutine_threadsafe`` and block on the result safely: the
bridge loop is independent of any caller loop, so there is no deadlock.

The bridge thread is started lazily on first use and reused across all
adapter wrappers. It survives until process exit (daemon thread).
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Awaitable, Coroutine, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_BRIDGE_LOOP: asyncio.AbstractEventLoop | None = None
_BRIDGE_THREAD: threading.Thread | None = None
_BRIDGE_LOCK = threading.Lock()
_BRIDGE_READY = threading.Event()


def _bridge_main() -> None:
    """Background-thread entry point. Owns a private event loop forever."""
    global _BRIDGE_LOOP
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _BRIDGE_LOOP = loop
    _BRIDGE_READY.set()
    try:
        loop.run_forever()
    finally:
        try:
            loop.close()
        except Exception:
            pass


def _ensure_bridge_loop() -> asyncio.AbstractEventLoop:
    """Lazily start the bridge loop / thread on first call."""
    global _BRIDGE_THREAD
    if _BRIDGE_LOOP is not None and _BRIDGE_LOOP.is_running():
        return _BRIDGE_LOOP
    with _BRIDGE_LOCK:
        if _BRIDGE_LOOP is not None and _BRIDGE_LOOP.is_running():
            return _BRIDGE_LOOP
        _BRIDGE_READY.clear()
        _BRIDGE_THREAD = threading.Thread(
            target=_bridge_main, name="synapse-sync-bridge", daemon=True
        )
        _BRIDGE_THREAD.start()
        # Wait up to 5s for the loop to come up. Local startup is sub-ms;
        # the timeout exists only to fail loud rather than hang forever.
        if not _BRIDGE_READY.wait(timeout=5.0):
            raise RuntimeError(
                "synapse._sync_bridge: bridge loop failed to start within 5s"
            )
        assert _BRIDGE_LOOP is not None
        return _BRIDGE_LOOP


def _resolve_target_loop() -> asyncio.AbstractEventLoop:
    """Pick the right loop to schedule a sync-wrapper coroutine onto.

    Decision tree:
      1. If the synapse runtime has an ``install_loop`` (the loop that
         created the bus + state pools) AND we are NOT currently running
         on it, prefer the install loop — that's where the connection
         pools live, so coros that talk to bus/state work natively. This
         is the common case for sync framework adapters invoked from a
         thread-pool worker (LangChain ``BaseTool.invoke`` from an
         ``asyncio.to_thread``-backed ainvoke fallback, CrewAI
         ``execute_sync`` from ``crew.kickoff()``).
      2. Otherwise fall back to the dedicated bridge loop. This handles:
         * No install loop yet (pure offline / early call before install).
         * We ARE on the install loop (scheduling there + blocking would
           deadlock — the M1 bug the bridge originally fixed).
    """
    # Lazy import — avoid cycle since intend.py imports from this module.
    try:
        from synapse.intend import _runtime as _rt
        install_loop = _rt.get("install_loop") if _rt.get("connected") else None
    except Exception:
        install_loop = None

    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if (
        install_loop is not None
        and install_loop.is_running()
        and running is not install_loop
    ):
        return install_loop
    return _ensure_bridge_loop()


def run_coro_blocking(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine to completion from a sync context.

    Safe to call from:
      - the main thread with no running loop (most adapter sync paths)
      - a worker thread with no running loop (CrewAI execute_sync, agno
        execute via to_thread, LangChain invoke fallback)
      - inside a coroutine on some OTHER event loop (the dangerous
        case the naive bridge breaks on)

    The coroutine runs on the install loop when possible (so bus + state
    pools work natively), falling back to the dedicated bridge loop when
    the install loop would deadlock or doesn't exist yet.

    Routing through the install loop fixes the asyncpg-cross-loop bug
    surfaced by Modal v4: the previous implementation always scheduled
    onto the bridge loop, which doesn't share connection pools with the
    install loop, producing ``ConnectionDoesNotExistError`` and
    ``Future ... attached to a different loop`` errors. The bridge is
    still used for the deadlock-avoidance case (sync wrapper invoked
    from inside the install loop's running coroutine).
    """
    target = _resolve_target_loop()
    fut = asyncio.run_coroutine_threadsafe(coro, target)
    return fut.result()


def shutdown_bridge() -> None:
    """Stop the bridge loop. Mostly useful for tests; production lets the
    daemon thread die at process exit."""
    global _BRIDGE_LOOP, _BRIDGE_THREAD
    if _BRIDGE_LOOP is None:
        return
    loop = _BRIDGE_LOOP
    try:
        loop.call_soon_threadsafe(loop.stop)
    except Exception:
        pass
    if _BRIDGE_THREAD is not None:
        _BRIDGE_THREAD.join(timeout=2.0)
    _BRIDGE_LOOP = None
    _BRIDGE_THREAD = None
    _BRIDGE_READY.clear()
