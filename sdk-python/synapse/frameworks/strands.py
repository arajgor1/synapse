"""AWS Strands Agents adapter for ``synapse.install(framework="strands")``.

Strands is AWS's open-source agent SDK (https://github.com/strands-agents/sdk-python).
Tools are decorated with ``@tool`` and the agent runs them through an
internal dispatcher. We patch the ``ToolHandler.handle_tool_call`` method
(or the equivalent dispatch entry point) so every tool invocation auto-
emits a Synapse INTENTION envelope with the right scope.

Agent identity:
    Strands' ``Agent.run()`` carries the agent name in its run-loop
    context. We read ``Agent.name`` from the calling instance when
    available; else fall back to env default.

Pattern matches the existing 11 framework adapters:
- patch a single dispatch entry point
- skip non-write tools (filter via is_write)
- wrap with ``async with intend(...)``
- mark scope via infer_scope on (tool_name, tool_args)

If Strands isn't installed, this module logs a warning and returns
silently — same UX as every other adapter.
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

_PATCHED = {"tool_handler": False}


def _session_id() -> str:
    return os.environ.get("SYNAPSE_SESSION_ID", "strands_default_session")


def _agent_id_default() -> str:
    from synapse.agent_context import current_agent_id
    return current_agent_id(default="strands_agent")


def _scope_from_call(tool_name: str, args: dict) -> list[str]:
    ev = AuditEvent(
        trace_id="strands", span_id="strands", agent_id="strands", session_id="strands",
        tool_name=tool_name, tool_args=args or {},
        ts_start_ms=0, ts_end_ms=0,
    )
    return infer_scope(ev) or [f"strands.tool.{tool_name}:w"]


def _is_write_call(tool_name: str, args: dict) -> bool:
    ev = AuditEvent(
        trace_id="strands", span_id="strands", agent_id="strands", session_id="strands",
        tool_name=tool_name, tool_args=args or {},
        ts_start_ms=0, ts_end_ms=0,
    )
    return is_write(ev)


def _wrap_handle_tool_call(original):
    """Patch ToolHandler.handle_tool_call — Strands' canonical tool
    dispatch path. Strands SDK >= 0.4 calls this once per tool invocation
    with (tool_use, agent) parameters where tool_use has .name and .input.
    """

    async def wrapper(self, *args, **kwargs):
        # Strands signature: handle_tool_call(self, tool_use, agent, ...)
        tool_use = args[0] if args else kwargs.get("tool_use")
        agent = args[1] if len(args) > 1 else kwargs.get("agent")

        # Tool name + args from the ToolUse object
        tool_name = (
            getattr(tool_use, "name", None)
            or getattr(tool_use, "tool_name", None)
            or "unknown_tool"
        )
        tool_input = (
            getattr(tool_use, "input", None)
            or getattr(tool_use, "tool_input", None)
            or {}
        )
        if not isinstance(tool_input, dict):
            try:
                tool_input = dict(tool_input)
            except Exception:
                tool_input = {"_arg0": str(tool_input)[:200]}

        # Read agent identity. Priority:
        #   1. ContextVar (race-free under concurrent agents)
        #   2. Strands-supplied agent.name / .agent_name
        #   3. SYNAPSE_AGENT_ID / SYNAPSE_DEFAULT_AGENT_ID (legacy)
        #   4. "strands_agent"
        from synapse.agent_context import _AGENT_CTX
        agent_id = (
            _AGENT_CTX.get()
            or getattr(agent, "name", None)
            or getattr(agent, "agent_name", None)
            or _agent_id_default()
        )

        if not _is_write_call(tool_name, tool_input):
            return await original(self, *args, **kwargs)

        scope = _scope_from_call(tool_name, tool_input)

        async with intend(
            scope=scope,
            agent=agent_id,
            session=_session_id(),
            expected_outcome=f"strands:{tool_name}",
            blocking=True,
            gate_ms=int(os.environ.get("SYNAPSE_GATE_MS", "200")),
        ) as i:
            try:
                result = await original(self, *args, **kwargs)
                # Best-effort state diff preview
                try:
                    preview = str(result)[:200]
                except Exception:
                    preview = "<unprintable>"
                i.set_state_diff({"output_preview": preview})
                return result
            except Exception as e:
                i.mark_failed(str(e))
                raise

    wrapper.__wrapped__ = original
    return wrapper


def _wrap_sync_dispatch(original):
    """Some Strands versions expose a synchronous dispatch fallback. Wrap
    that too, scheduling onto the install loop where possible."""

    def wrapper(self, *args, **kwargs):
        tool_use = args[0] if args else kwargs.get("tool_use")
        agent = args[1] if len(args) > 1 else kwargs.get("agent")
        tool_name = getattr(tool_use, "name", None) or "unknown_tool"
        tool_input = getattr(tool_use, "input", None) or {}
        if not isinstance(tool_input, dict):
            try:
                tool_input = dict(tool_input)
            except Exception:
                tool_input = {"_arg0": str(tool_input)[:200]}

        if not _is_write_call(tool_name, tool_input):
            return original(self, *args, **kwargs)

        scope = _scope_from_call(tool_name, tool_input)
        from synapse.agent_context import _AGENT_CTX
        agent_id = (
            _AGENT_CTX.get()
            or getattr(agent, "name", None)
            or _agent_id_default()
        )

        async def _run():
            async with intend(
                scope=scope, agent=agent_id, session=_session_id(),
                expected_outcome=f"strands:{tool_name}",
                blocking=True,
                gate_ms=int(os.environ.get("SYNAPSE_GATE_MS", "200")),
            ) as i:
                try:
                    result = await asyncio.to_thread(original, self, *args, **kwargs)
                    i.set_state_diff({"output_preview": str(result)[:200]})
                    return result
                except Exception as e:
                    i.mark_failed(str(e))
                    raise

        # Bridge loop avoids deadlock if dispatch is reached from a
        # caller's running loop.
        from synapse.frameworks._sync_bridge import run_coro_blocking
        return run_coro_blocking(_run())

    wrapper.__wrapped__ = original
    return wrapper


def _wrap_module_level_async(original):
    """Patch a module-level async function. Strands' real SDK exposes
    `_handle_tool_execution` and `event_loop_cycle` as module functions,
    not class methods. The signatures vary across versions but the
    relevant ToolUse object is generally findable in the args."""

    async def wrapper(*args, **kwargs):
        # Heuristic: scan args/kwargs for a ToolUse-shaped object
        tool_use = None
        for cand in list(args) + list(kwargs.values()):
            if hasattr(cand, "name") and hasattr(cand, "input"):
                tool_use = cand
                break
            if isinstance(cand, dict) and "name" in cand and ("input" in cand or "tool_use_id" in cand):
                tool_use = type("TU", (), cand)
                break

        if tool_use is None:
            # Cannot find a tool — fall through unwrapped
            async for ev in original(*args, **kwargs):
                yield ev
            return

        tool_name = (
            getattr(tool_use, "name", None)
            or (tool_use.get("name") if isinstance(tool_use, dict) else None)
            or "unknown_tool"
        )
        tool_input = (
            getattr(tool_use, "input", None)
            or (tool_use.get("input") if isinstance(tool_use, dict) else None)
            or {}
        )
        if not isinstance(tool_input, dict):
            try:
                tool_input = dict(tool_input)
            except Exception:
                tool_input = {"_arg0": str(tool_input)[:200]}

        # Module-level dispatch — no agent object available, fall back
        # to ContextVar / env vars via the standard helper.
        agent_id = _agent_id_default()

        if not _is_write_call(tool_name, tool_input):
            async for ev in original(*args, **kwargs):
                yield ev
            return

        scope = _scope_from_call(tool_name, tool_input)

        async with intend(
            scope=scope,
            agent=agent_id,
            session=_session_id(),
            expected_outcome=f"strands:{tool_name}",
            blocking=True,
            gate_ms=int(os.environ.get("SYNAPSE_GATE_MS", "200")),
        ) as i:
            try:
                async for ev in original(*args, **kwargs):
                    yield ev
                i.set_state_diff({"tool": tool_name})
            except Exception as e:
                i.mark_failed(str(e))
                raise

    wrapper.__wrapped__ = original
    return wrapper


def _install_strands(opts: dict[str, Any]) -> None:
    if _PATCHED["tool_handler"]:
        return

    # Strands SDK 1.x: dispatch is in strands.event_loop.event_loop as
    # module-level functions, not on a ToolHandler class.
    try:
        import strands.event_loop.event_loop as ev_mod  # type: ignore[import-not-found]
    except ImportError:
        # Older / alternate paths
        try:
            from strands.tools.handler import ToolHandler  # type: ignore[import-not-found]
            handler_cls = ToolHandler
            ev_mod = None
        except ImportError:
            try:
                from strands.tools import ToolHandler  # type: ignore[import-not-found]
                handler_cls = ToolHandler
                ev_mod = None
            except ImportError:
                logger.warning(
                    "synapse.install(framework='strands'): strands SDK not "
                    "installed. `pip install strands-agents`."
                )
                return
    else:
        handler_cls = None

    # Modern Strands: patch _handle_tool_execution at module level
    if ev_mod is not None and hasattr(ev_mod, "_handle_tool_execution"):
        original = ev_mod._handle_tool_execution
        ev_mod._handle_tool_execution = _wrap_module_level_async(original)
        _PATCHED["tool_handler"] = True
        logger.info(
            "synapse.install(framework='strands'): patched module-level "
            "strands.event_loop.event_loop._handle_tool_execution"
        )
        return

    # Older Strands: patch class method
    if handler_cls is not None and hasattr(handler_cls, "handle_tool_call"):
        if asyncio.iscoroutinefunction(handler_cls.handle_tool_call):
            handler_cls.handle_tool_call = _wrap_handle_tool_call(handler_cls.handle_tool_call)
        else:
            handler_cls.handle_tool_call = _wrap_sync_dispatch(handler_cls.handle_tool_call)
        _PATCHED["tool_handler"] = True
        logger.info(
            "synapse.install(framework='strands'): patched %s.handle_tool_call",
            handler_cls.__name__,
        )
        return

    logger.warning(
        "synapse.install(framework='strands'): could not find a known "
        "Strands dispatch entry point. Probed: "
        "strands.event_loop.event_loop._handle_tool_execution, "
        "strands.tools.handler.ToolHandler.handle_tool_call. "
        "Open an issue with your Strands version."
    )


register_framework("strands", _install_strands)
