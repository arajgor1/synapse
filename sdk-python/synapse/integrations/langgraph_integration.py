"""LangGraph integration — wrap any node so it participates in Synapse coordination.

Usage:
    from synapse.integrations import synapse_node

    @synapse_node(
        agent_id="reviewer",
        scope=["repo.auth.middleware:r"],
        expected_outcome="Review middleware for race conditions",
    )
    def review_node(state: dict) -> dict:
        # ... your existing LangGraph node body ...
        return {"review": "ok"}

The decorator:
- Auto-registers the agent with Synapse on first call (idempotent)
- Emits INTENTION before the body runs
- If `blocking=True`, waits up to `gate_ms` for CONFLICT/BLOCK signals
- On conflict, raises `SynapseConflict` (caller can catch and pivot in graph logic)
- Emits RESOLUTION after success / failure

The integration does not require any LangGraph imports — it works with any
function that takes a state dict and returns a state dict. So it's compatible
with LangGraph, custom workflow runners, or plain async functions.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import threading
from typing import Any, Awaitable, Callable, Optional

from synapse.adapters import MockAdapter
from synapse.adapters.base import InferenceAdapter
from synapse.agent import Agent
from synapse.bus import Bus
from synapse.messages import Conflict
from synapse.state import StateGraph

logger = logging.getLogger(__name__)


class SynapseConflict(Exception):
    """Raised by a synapse_node when a CONFLICT arrives during the gate window.

    The conflict object is attached as `.conflict`. Caller can catch this in
    LangGraph's conditional edge logic to route to a pivot node.
    """

    def __init__(self, conflict: Conflict) -> None:
        self.conflict = conflict
        super().__init__(
            f"Scope conflict on {conflict.overlapping_scopes}: "
            f"{conflict.suggested_resolution}"
        )


# Module-level shared connections so multiple decorated nodes don't each open
# a Bus + StateGraph. Connection is lazy on first synapse_node call.
_singleton_lock = threading.Lock()
_singleton: dict[str, Any] = {"bus": None, "state": None, "agents": {}}


async def _ensure_connections() -> tuple[Bus, StateGraph]:
    """Idempotently connect Bus + StateGraph. Returns the shared instances."""
    if _singleton["bus"] is None:
        bus = Bus(os.getenv("SYNAPSE_REDIS_URL", "redis://localhost:6379/0"))
        await bus.connect()
        _singleton["bus"] = bus
    if _singleton["state"] is None:
        state = StateGraph(os.getenv(
            "SYNAPSE_POSTGRES_DSN",
            "postgresql://synapse:synapse_dev@localhost:5432/synapse",
        ))
        await state.connect()
        _singleton["state"] = state
    return _singleton["bus"], _singleton["state"]


async def _ensure_agent(
    *,
    agent_id: str,
    session_id: str,
    backend: InferenceAdapter,
    subscribes: list[str],
    scopes_owned: list[str],
) -> Agent:
    key = f"{session_id}:{agent_id}"
    if key in _singleton["agents"]:
        return _singleton["agents"][key]
    bus, state = await _ensure_connections()
    agent = Agent(
        id=agent_id,
        session=session_id,
        backend=backend,
        subscribes=subscribes,
        scopes_owned=scopes_owned,
        bus=bus,
        state=state,
    )
    # Use the lifecycle's _register manually since we never close the agent
    await agent._connect()
    await agent._register()
    _singleton["agents"][key] = agent
    return agent


def synapse_node(
    *,
    agent_id: str,
    scope: list[str],
    expected_outcome: str,
    session_id: Optional[str] = None,
    backend: Optional[InferenceAdapter] = None,
    subscribes: Optional[list[str]] = None,
    scopes_owned: Optional[list[str]] = None,
    blocking: bool = True,
    gate_ms: int = 50,
):
    """Decorator factory. Returns a decorator that wraps a function (sync or
    async, taking and returning a state dict) with Synapse coordination.

    Args:
        agent_id: Stable agent identifier within the session.
        scope: Scope claim for this node's INTENTION.
        expected_outcome: Free-text description of what this node aims to do.
        session_id: Defaults to env SYNAPSE_SESSION_ID; required either way.
        backend: Inference adapter for the agent (default MockAdapter).
        blocking: If True, wait gate_ms for CONFLICT/BLOCK before running body.
        gate_ms: Pre-execution gate window in ms.
    """
    sid_default = session_id or os.environ.get("SYNAPSE_SESSION_ID")
    backend_default = backend or MockAdapter()

    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        is_coro = asyncio.iscoroutinefunction(func)

        async def _async_invoke(*args: Any, **kwargs: Any) -> Any:
            sid = sid_default
            if sid is None:
                raise RuntimeError(
                    "synapse_node needs a session_id (pass session_id=... "
                    "or set SYNAPSE_SESSION_ID env)."
                )
            agent = await _ensure_agent(
                agent_id=agent_id,
                session_id=sid,
                backend=backend_default,
                subscribes=subscribes or [],
                scopes_owned=scopes_owned or [],
            )
            int_id, conflicts = await agent.emit_intention(
                action={"description": f"langgraph_node:{func.__name__}"},
                scope=scope,
                expected_outcome=expected_outcome,
                blocking=blocking,
                gate_ms=gate_ms,
            )
            if conflicts:
                raise SynapseConflict(conflicts[0])
            try:
                if is_coro:
                    result = await func(*args, **kwargs)
                else:
                    # Run sync function in default executor so we don't block loop
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, lambda: func(*args, **kwargs))
                await agent.emit_resolution(intention_id=int_id, outcome="success")
                return result
            except Exception as e:
                await agent.emit_resolution(
                    intention_id=int_id, outcome="failure",
                    state_diff={"error": str(e)[:200]},
                )
                raise

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Detect whether we're in an async context already
            try:
                loop = asyncio.get_running_loop()
                # Schedule and return the awaitable so the caller can await it
                return _async_invoke(*args, **kwargs)
            except RuntimeError:
                # No running loop — run synchronously
                return asyncio.run(_async_invoke(*args, **kwargs))

        return wrapper

    return deco
