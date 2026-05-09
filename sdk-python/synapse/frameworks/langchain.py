"""LangChain adapter for ``synapse.install(framework="langchain")``.

LangChain (the broader framework, separate from LangGraph) routes
tool execution through ``langchain_core.tools.BaseTool.invoke`` and
``ainvoke``. Patching at the abstract base catches every concrete
tool subclass automatically (StructuredTool, FunctionTool, retrievers,
custom tools).

Verified against langchain-core 0.3.x.

Note: this is DISTINCT from the LangGraph adapter
(synapse.frameworks.langgraph). LangGraph uses LangChain's callback
system; this LangChain adapter patches the BaseTool dispatch directly.
Use both together if your stack uses both LangChain Runnables AND
LangGraph state machines.

We deliberately ship this BEFORE Semantica's "coming soon" LangChain
integration. LangChain remains the largest agent ecosystem by adoption,
making this a high-impact adapter.
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


_PATCHED = {"basetool_invoke": False}
_INSTALL_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _session_id() -> str:
    return os.environ.get("SYNAPSE_SESSION_ID", "langchain_default_session")


def _agent_id_default() -> str:
    return os.environ.get("SYNAPSE_AGENT_ID") or os.environ.get(
        "SYNAPSE_DEFAULT_AGENT_ID", "langchain_agent"
    )


def _scope_from_call(tool_name: str, args: dict) -> list[str]:
    ev = AuditEvent(
        trace_id="lc", span_id="lc", agent_id="lc", session_id="lc",
        tool_name=tool_name, tool_args=args or {},
        ts_start_ms=0, ts_end_ms=0,
    )
    return infer_scope(ev) or [f"langchain.tool.{tool_name}:w"]


def _is_write_call(tool_name: str, args: dict) -> bool:
    ev = AuditEvent(
        trace_id="lc", span_id="lc", agent_id="lc", session_id="lc",
        tool_name=tool_name, tool_args=args or {},
        ts_start_ms=0, ts_end_ms=0,
    )
    return is_write(ev)


def _coerce_tool_input(tool_input: Any) -> dict:
    """LangChain BaseTool.invoke accepts str | dict | ToolCall."""
    if tool_input is None:
        return {}
    if isinstance(tool_input, dict):
        # ToolCall has shape {"name": ..., "args": {...}, "id": ..., "type": "tool_call"}
        if "args" in tool_input and isinstance(tool_input.get("args"), dict):
            return dict(tool_input["args"])
        return dict(tool_input)
    if isinstance(tool_input, str):
        return {"_input": tool_input[:500]}
    return {"_input": str(tool_input)[:500]}


def _wrap_invoke(original):
    def wrapper(self, tool_input=None, config=None, **kwargs):
        tool_name = getattr(self, "name", None) or type(self).__name__
        tool_args = _coerce_tool_input(tool_input)

        if not _is_write_call(tool_name, tool_args):
            return original(self, tool_input, config, **kwargs)

        scope = _scope_from_call(tool_name, tool_args)
        agent_id = _agent_id_default()

        async def _run():
            async with intend(
                scope=scope, agent=agent_id, session=_session_id(),
                expected_outcome=f"langchain:{tool_name}",
                blocking=True,
                gate_ms=int(os.environ.get("SYNAPSE_GATE_MS", "200")),
            ) as i:
                try:
                    result = await asyncio.to_thread(
                        original, self, tool_input, config, **kwargs
                    )
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


def _wrap_ainvoke(original):
    async def wrapper(self, tool_input=None, config=None, **kwargs):
        tool_name = getattr(self, "name", None) or type(self).__name__
        tool_args = _coerce_tool_input(tool_input)

        if not _is_write_call(tool_name, tool_args):
            return await original(self, tool_input, config, **kwargs)

        scope = _scope_from_call(tool_name, tool_args)
        agent_id = _agent_id_default()

        async with intend(
            scope=scope, agent=agent_id, session=_session_id(),
            expected_outcome=f"langchain:{tool_name}",
            blocking=True,
            gate_ms=int(os.environ.get("SYNAPSE_GATE_MS", "200")),
        ) as i:
            try:
                result = await original(self, tool_input, config, **kwargs)
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


def _install_langchain(opts: dict[str, Any]) -> None:
    global _INSTALL_LOOP
    try:
        _INSTALL_LOOP = asyncio.get_running_loop()
    except RuntimeError:
        _INSTALL_LOOP = None

    if _PATCHED["basetool_invoke"]:
        return

    try:
        from langchain_core.tools import BaseTool  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "synapse.install(framework='langchain'): langchain-core not installed. "
            "`pip install langchain-core`."
        )
        return

    BaseTool.invoke = _wrap_invoke(BaseTool.invoke)
    if hasattr(BaseTool, "ainvoke"):
        BaseTool.ainvoke = _wrap_ainvoke(BaseTool.ainvoke)
    _PATCHED["basetool_invoke"] = True
    logger.info(
        "synapse.install(framework='langchain'): patched "
        "langchain_core.tools.BaseTool.{invoke,ainvoke} — every tool call "
        "across every concrete tool subclass (StructuredTool, FunctionTool, "
        "custom tools) now participates in Synapse coordination."
    )


register_framework("langchain", _install_langchain)
