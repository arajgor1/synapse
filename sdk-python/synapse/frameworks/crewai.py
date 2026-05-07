"""CrewAI adapter for ``synapse.install(framework="crewai")``.

Wraps CrewAI's Task execution: every ``Task.execute_sync()`` / ``execute_async()``
gets intercepted, emits INTENTION → CONFLICT detection → run task → RESOLUTION,
all via the universal ``synapse.intend()`` flow.

Strategy: monkey-patch ``crewai.Task.execute_sync`` and ``execute_async``
once at install time. Tasks created after install (or already-existing
ones) inherit the wrapped method via the class.

If the user wants per-task control, they keep using the v0.1 ``synapse_task``
decorator (still supported). This adapter is for users who want global
auto-instrumentation.

The agent identity for each task comes from ``task.agent.role`` (CrewAI's
canonical role string).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

from synapse.intend import intend
from synapse.audit.events import AuditEvent, is_write
from synapse.audit.scope_inference import infer_scope
from synapse.install import register_framework

logger = logging.getLogger(__name__)


_PATCHED = {"sync": False, "async": False}
_INSTALL_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _scope_from_task(task: Any) -> list[str]:
    """Map a CrewAI Task to a scope claim.

    Heuristics:
      - If task.expected_output mentions a file path, use repo.fs.<path>:w
      - Else use crewai.task.<id>:w as a generic scope
    """
    desc = (getattr(task, "description", "") or "").lower()
    expected = (getattr(task, "expected_output", "") or "").lower()
    text = f"{desc} {expected}"

    import re
    m = re.search(r"([a-z0-9_./-]+\.(?:py|ts|js|md|yaml|yml|json|sql|html|css|tsx|jsx))", text)
    if m:
        path = m.group(1)
        return [f"repo.fs.{path}:w"]

    task_id = getattr(task, "id", None) or hex(id(task))[2:]
    return [f"crewai.task.{task_id}:w"]


def _agent_id_from_task(task: Any) -> str:
    agent = getattr(task, "agent", None)
    if agent is not None:
        for k in ("role", "name", "id"):
            v = getattr(agent, k, None)
            if v:
                return str(v).replace(" ", "_").lower()
    return "crewai_default"


def _session_id() -> str:
    return os.environ.get("SYNAPSE_SESSION_ID", "crewai_default_session")


def _wrap_sync(original_execute_sync):
    def wrapper(self, *args, **kwargs):
        # Build a synthetic AuditEvent so we can reuse scope inference + is_write
        agent_id = _agent_id_from_task(self)
        scope = _scope_from_task(self)
        expected = str(getattr(self, "expected_output", "") or f"crewai task {agent_id}")[:120]

        # CrewAI's execute_sync is sync — we need to drive intend() in an event loop
        async def _run():
            async with intend(
                scope=scope,
                agent=agent_id,
                session=_session_id(),
                expected_outcome=expected,
                blocking=True,
                gate_ms=int(os.environ.get("SYNAPSE_GATE_MS", "200")),
            ) as i:
                # Run the original sync method on a thread so we don't block the loop
                result = await asyncio.to_thread(original_execute_sync, self, *args, **kwargs)
                if i.has_conflicts:
                    logger.warning(
                        "synapse.crewai: CONFLICT on task agent=%s scope=%s "
                        "(%d conflicts) — proceeding (failOnConflict not set)",
                        agent_id, scope, len(i.conflicts),
                    )
                i.set_state_diff({"output_preview": str(result)[:200]})
                return result

        # Always route through the install-time loop. CrewAI Task.execute_sync
        # runs in worker threads (kicked off by crew.kickoff()), so each call
        # has no running loop in its own thread — naive asyncio.run() would
        # spawn a fresh loop per call, breaking bus/state pool isolation.
        target_loop = _INSTALL_LOOP
        if target_loop is None or not target_loop.is_running():
            try:
                target_loop = asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(_run())
        return asyncio.run_coroutine_threadsafe(_run(), target_loop).result()

    wrapper.__wrapped__ = original_execute_sync
    return wrapper


def _wrap_async(original_execute_async):
    async def wrapper(self, *args, **kwargs):
        agent_id = _agent_id_from_task(self)
        scope = _scope_from_task(self)
        expected = str(getattr(self, "expected_output", "") or f"crewai task {agent_id}")[:120]

        async with intend(
            scope=scope,
            agent=agent_id,
            session=_session_id(),
            expected_outcome=expected,
            blocking=True,
            gate_ms=int(os.environ.get("SYNAPSE_GATE_MS", "200")),
        ) as i:
            if i.has_conflicts:
                logger.warning(
                    "synapse.crewai: CONFLICT on task agent=%s scope=%s",
                    agent_id, scope,
                )
            result = await original_execute_async(self, *args, **kwargs)
            i.set_state_diff({"output_preview": str(result)[:200]})
            return result

    wrapper.__wrapped__ = original_execute_async
    return wrapper


def _install_crewai(opts: dict[str, Any]) -> None:
    global _INSTALL_LOOP
    try:
        _INSTALL_LOOP = asyncio.get_event_loop()
    except RuntimeError:
        _INSTALL_LOOP = None

    try:
        from crewai import Task  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "synapse.install(framework='crewai'): crewai not installed. "
            "`pip install crewai`. Falling back to manual synapse.intend()."
        )
        return

    if not _PATCHED["sync"] and hasattr(Task, "execute_sync"):
        Task.execute_sync = _wrap_sync(Task.execute_sync)
        _PATCHED["sync"] = True

    if not _PATCHED["async"] and hasattr(Task, "execute_async"):
        Task.execute_async = _wrap_async(Task.execute_async)
        _PATCHED["async"] = True

    logger.info(
        "synapse.install(framework='crewai'): patched Task.execute_{sync,async}; "
        "all CrewAI tasks created from this point participate in Synapse coordination."
    )


register_framework("crewai", _install_crewai)
