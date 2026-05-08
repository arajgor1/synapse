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
_INSTALL_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _session_id() -> str:
    return os.environ.get("SYNAPSE_SESSION_ID", "strands_default_session")


def _agent_id_default() -> str:
    return os.environ.get("SYNAPSE_DEFAULT_AGENT_ID", "strands_agent")


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

        # Read agent identity off the run-context
        agent_id = (
            os.environ.get("SYNAPSE_AGENT_ID")
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
        agent_id = (
            os.environ.get("SYNAPSE_AGENT_ID")
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

        target = _INSTALL_LOOP
        if target is None or not target.is_running():
            try:
                target = asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(_run())
        return asyncio.run_coroutine_threadsafe(_run(), target).result()

    wrapper.__wrapped__ = original
    return wrapper


def _install_strands(opts: dict[str, Any]) -> None:
    global _INSTALL_LOOP
    try:
        _INSTALL_LOOP = asyncio.get_event_loop()
    except RuntimeError:
        _INSTALL_LOOP = None

    if _PATCHED["tool_handler"]:
        return

    handler_cls = None
    try:
        # Strands SDK 0.4+ canonical path
        from strands.tools.handler import ToolHandler  # type: ignore[import-not-found]
        handler_cls = ToolHandler
    except ImportError:
        try:
            # Older / alternative path
            from strands.tools import ToolHandler  # type: ignore[import-not-found]
            handler_cls = ToolHandler
        except ImportError:
            try:
                # Some versions expose dispatch on Agent directly
                from strands import Agent  # type: ignore[import-not-found]
                handler_cls = Agent
            except ImportError:
                logger.warning(
                    "synapse.install(framework='strands'): strands SDK not "
                    "installed. `pip install strands-agents`."
                )
                return

    # Patch async path if present
    if hasattr(handler_cls, "handle_tool_call") and asyncio.iscoroutinefunction(
        handler_cls.handle_tool_call
    ):
        handler_cls.handle_tool_call = _wrap_handle_tool_call(handler_cls.handle_tool_call)
        _PATCHED["tool_handler"] = True
        logger.info(
            "synapse.install(framework='strands'): patched async %s.handle_tool_call",
            handler_cls.__name__,
        )
        return

    # Sync fallback
    if hasattr(handler_cls, "handle_tool_call"):
        handler_cls.handle_tool_call = _wrap_sync_dispatch(handler_cls.handle_tool_call)
        _PATCHED["tool_handler"] = True
        logger.info(
            "synapse.install(framework='strands'): patched sync %s.handle_tool_call",
            handler_cls.__name__,
        )
        return

    # Last-resort: patch the canonical _dispatch path
    for candidate in ("_dispatch_tool", "dispatch_tool", "_invoke_tool"):
        if hasattr(handler_cls, candidate):
            orig = getattr(handler_cls, candidate)
            wrapped = (
                _wrap_handle_tool_call(orig)
                if asyncio.iscoroutinefunction(orig)
                else _wrap_sync_dispatch(orig)
            )
            setattr(handler_cls, candidate, wrapped)
            _PATCHED["tool_handler"] = True
            logger.info(
                "synapse.install(framework='strands'): patched %s.%s",
                handler_cls.__name__, candidate,
            )
            return

    logger.warning(
        "synapse.install(framework='strands'): could not find a "
        "tool-dispatch hook on %s. Open an issue with your Strands "
        "version so we can add support.",
        handler_cls.__name__,
    )


register_framework("strands", _install_strands)
