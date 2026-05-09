"""Agno adapter for ``synapse.install(framework="agno")``.

Agno (https://docs.agno.com) is a framework for building model-agnostic
agents with strong workflow primitives. It dispatches tool calls via
``agno.tools.FunctionCall.execute()`` (sync) and ``aexecute()`` (async).

Patching FunctionCall.execute / aexecute catches every tool call across
every Agent / Workflow / Toolkit since they all funnel through the same
FunctionCall path.

Verified against agno 2.6.5.

We deliberately ship this BEFORE Semantica's "coming soon" Agno
integration, since Synapse's audit + coordination is purpose-built
for the multi-agent collision case and Agno's workflow primitives
(Parallel, Loop, Router) make multi-agent state-sharing very common.
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


_PATCHED = {"function_call_execute": False}
_INSTALL_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _session_id() -> str:
    return os.environ.get("SYNAPSE_SESSION_ID", "agno_default_session")


def _agent_id_default() -> str:
    return os.environ.get("SYNAPSE_AGENT_ID") or os.environ.get(
        "SYNAPSE_DEFAULT_AGENT_ID", "agno_agent"
    )


def _scope_from_call(tool_name: str, args: dict) -> list[str]:
    ev = AuditEvent(
        trace_id="agno", span_id="agno", agent_id="agno", session_id="agno",
        tool_name=tool_name, tool_args=args or {},
        ts_start_ms=0, ts_end_ms=0,
    )
    return infer_scope(ev) or [f"agno.tool.{tool_name}:w"]


def _is_write_call(tool_name: str, args: dict) -> bool:
    ev = AuditEvent(
        trace_id="agno", span_id="agno", agent_id="agno", session_id="agno",
        tool_name=tool_name, tool_args=args or {},
        ts_start_ms=0, ts_end_ms=0,
    )
    return is_write(ev)


def _extract_call_metadata(self_call: Any) -> tuple[str, dict]:
    """Pull (tool_name, args) off an agno.tools.FunctionCall instance."""
    fn = getattr(self_call, "function", None)
    tool_name = (
        getattr(fn, "name", None) if fn is not None else None
    ) or getattr(self_call, "name", None) or "agno_tool"
    args = getattr(self_call, "arguments", None) or {}
    if not isinstance(args, dict):
        try:
            args = dict(args)
        except Exception:
            args = {"_arg": str(args)[:200]}
    return tool_name, args


def _wrap_aexecute(original):
    async def wrapper(self, *args, **kwargs):
        tool_name, tool_args = _extract_call_metadata(self)

        if not _is_write_call(tool_name, tool_args):
            return await original(self, *args, **kwargs)

        scope = _scope_from_call(tool_name, tool_args)
        agent_id = _agent_id_default()

        async with intend(
            scope=scope,
            agent=agent_id,
            session=_session_id(),
            expected_outcome=f"agno:{tool_name}",
            blocking=True,
            gate_ms=int(os.environ.get("SYNAPSE_GATE_MS", "200")),
        ) as i:
            try:
                result = await original(self, *args, **kwargs)
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


def _wrap_execute_sync(original):
    """Sync execute() wrapper — schedule the intend() onto the install loop."""

    def wrapper(self, *args, **kwargs):
        tool_name, tool_args = _extract_call_metadata(self)

        if not _is_write_call(tool_name, tool_args):
            return original(self, *args, **kwargs)

        scope = _scope_from_call(tool_name, tool_args)
        agent_id = _agent_id_default()

        async def _run():
            async with intend(
                scope=scope, agent=agent_id, session=_session_id(),
                expected_outcome=f"agno:{tool_name}",
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


def _install_agno(opts: dict[str, Any]) -> None:
    global _INSTALL_LOOP
    try:
        _INSTALL_LOOP = asyncio.get_running_loop()
    except RuntimeError:
        _INSTALL_LOOP = None

    if _PATCHED["function_call_execute"]:
        return

    try:
        from agno.tools import FunctionCall  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "synapse.install(framework='agno'): agno not installed. "
            "`pip install agno`."
        )
        return

    if hasattr(FunctionCall, "aexecute"):
        FunctionCall.aexecute = _wrap_aexecute(FunctionCall.aexecute)
    if hasattr(FunctionCall, "execute"):
        FunctionCall.execute = _wrap_execute_sync(FunctionCall.execute)

    _PATCHED["function_call_execute"] = True
    logger.info(
        "synapse.install(framework='agno'): patched "
        "agno.tools.FunctionCall.{execute,aexecute} — every tool call across "
        "every Agent/Workflow/Toolkit now participates in Synapse coordination."
    )


register_framework("agno", _install_agno)
