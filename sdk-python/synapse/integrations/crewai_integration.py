"""CrewAI integration — wrap a CrewAI Task or any callable so that its
execution participates in Synapse coordination.

Usage with CrewAI:

    from crewai import Task
    from synapse.integrations import synapse_task

    raw_task = Task(
        description="Refactor auth middleware for rate limiting",
        agent=auth_agent,
        expected_output="Refactored middleware module",
    )

    # Wrap before passing to crew.kickoff()
    coordinated_task = synapse_task(
        agent_id="auth_engineer",
        scope=["repo.auth.middleware:w"],
        expected_outcome="Refactor middleware",
    )(raw_task)

The integration pattern:
- On task.execute_sync() / .execute_async(), emit INTENTION first
- Wait for the gate window if blocking
- If CONFLICT, raise SynapseConflict (CrewAI catches errors and surfaces them)
- After execute returns, emit RESOLUTION

Like the LangGraph integration, this works without a hard dependency on
crewai — we duck-type any object that has .execute or is itself callable.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
from typing import Any, Callable, Optional

from synapse.adapters import MockAdapter
from synapse.adapters.base import InferenceAdapter
from synapse.integrations.langgraph_integration import (
    SynapseConflict,
    _ensure_agent,
)

logger = logging.getLogger(__name__)


def synapse_task(
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
    """Wrap a CrewAI Task (or any callable) with Synapse coordination.

    Returns a function that takes the task object/callable and returns a
    Synapse-coordinated wrapper. If the input is a CrewAI Task, .execute() is
    intercepted; otherwise the input is treated as a plain callable.
    """
    sid_default = session_id or os.environ.get("SYNAPSE_SESSION_ID")
    backend_default = backend or MockAdapter()

    def wrap(target: Any) -> Any:
        # Detect: does this look like a CrewAI Task? Has .execute()
        if hasattr(target, "execute_sync") or hasattr(target, "execute"):
            return _wrap_task_object(
                target, agent_id, scope, expected_outcome,
                sid_default, backend_default,
                subscribes or [], scopes_owned or [], blocking, gate_ms,
            )
        if callable(target):
            return _wrap_callable(
                target, agent_id, scope, expected_outcome,
                sid_default, backend_default,
                subscribes or [], scopes_owned or [], blocking, gate_ms,
            )
        raise TypeError(
            "synapse_task expects a CrewAI Task or a callable; got "
            f"{type(target).__name__}"
        )

    return wrap


# ---------------------------------------------------------------------------
def _wrap_task_object(
    task: Any,
    agent_id: str,
    scope: list[str],
    expected_outcome: str,
    sid_default: Optional[str],
    backend_default: InferenceAdapter,
    subscribes: list[str],
    scopes_owned: list[str],
    blocking: bool,
    gate_ms: int,
) -> Any:
    """Monkey-patch the task's execute methods to emit Synapse messages."""
    original_execute_sync = getattr(task, "execute_sync", None)
    original_execute_async = getattr(task, "execute_async", None)

    async def _coordinated_execute_async(*args: Any, **kwargs: Any) -> Any:
        sid = sid_default or os.environ.get("SYNAPSE_SESSION_ID")
        if sid is None:
            raise RuntimeError("synapse_task needs SYNAPSE_SESSION_ID or session_id=")
        agent = await _ensure_agent(
            agent_id=agent_id, session_id=sid, backend=backend_default,
            subscribes=subscribes, scopes_owned=scopes_owned,
        )
        int_id, conflicts = await agent.emit_intention(
            action={"description": f"crewai_task:{getattr(task, 'description', '<anon>')}"},
            scope=scope, expected_outcome=expected_outcome,
            blocking=blocking, gate_ms=gate_ms,
        )
        if conflicts:
            raise SynapseConflict(conflicts[0])
        try:
            if original_execute_async:
                result = await original_execute_async(*args, **kwargs)
            else:
                # Fall back: run the sync version in executor
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None, lambda: original_execute_sync(*args, **kwargs)
                )
            await agent.emit_resolution(intention_id=int_id, outcome="success")
            return result
        except Exception as e:
            await agent.emit_resolution(
                intention_id=int_id, outcome="failure",
                state_diff={"error": str(e)[:200]},
            )
            raise

    def _coordinated_execute_sync(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(_coordinated_execute_async(*args, **kwargs))

    if original_execute_sync:
        task.execute_sync = _coordinated_execute_sync  # type: ignore[attr-defined]
    if original_execute_async:
        task.execute_async = _coordinated_execute_async  # type: ignore[attr-defined]
    return task


def _wrap_callable(
    func: Callable[..., Any],
    agent_id: str,
    scope: list[str],
    expected_outcome: str,
    sid_default: Optional[str],
    backend_default: InferenceAdapter,
    subscribes: list[str],
    scopes_owned: list[str],
    blocking: bool,
    gate_ms: int,
) -> Callable[..., Any]:
    is_coro = asyncio.iscoroutinefunction(func)

    async def _async_invoke(*args: Any, **kwargs: Any) -> Any:
        sid = sid_default or os.environ.get("SYNAPSE_SESSION_ID")
        if sid is None:
            raise RuntimeError("synapse_task needs SYNAPSE_SESSION_ID or session_id=")
        agent = await _ensure_agent(
            agent_id=agent_id, session_id=sid, backend=backend_default,
            subscribes=subscribes, scopes_owned=scopes_owned,
        )
        int_id, conflicts = await agent.emit_intention(
            action={"description": f"crewai_callable:{func.__name__}"},
            scope=scope, expected_outcome=expected_outcome,
            blocking=blocking, gate_ms=gate_ms,
        )
        if conflicts:
            raise SynapseConflict(conflicts[0])
        try:
            if is_coro:
                result = await func(*args, **kwargs)
            else:
                loop = asyncio.get_running_loop()
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
        try:
            asyncio.get_running_loop()
            return _async_invoke(*args, **kwargs)
        except RuntimeError:
            return asyncio.run(_async_invoke(*args, **kwargs))

    return wrapper
