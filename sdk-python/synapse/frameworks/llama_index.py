"""LlamaIndex adapter for ``synapse.install(framework="llama_index")``.

LlamaIndex (https://docs.llamaindex.ai) is a framework for context-augmented
LLM applications with strong agent + tool primitives. Tool calls funnel
through ``llama_index.core.tools.FunctionTool.call`` (sync) and
``acall`` (async).

Patching FunctionTool.call / acall catches every tool dispatch across
every Agent (ReActAgent, OpenAIAgent, FunctionCallingAgent, etc.).

Verified against llama-index-core 0.11+.

We deliberately ship this BEFORE Semantica's "coming soon" LlamaIndex
integration. LlamaIndex's heavy use across RAG + agent stacks makes
this a strong adoption channel.
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


_PATCHED = {"function_tool_call": False}


def _session_id() -> str:
    return os.environ.get("SYNAPSE_SESSION_ID", "llama_index_default_session")


def _agent_id_default() -> str:
    from synapse.agent_context import current_agent_id
    return current_agent_id(default="llama_index_agent")


def _scope_from_call(tool_name: str, args: dict) -> list[str]:
    ev = AuditEvent(
        trace_id="li", span_id="li", agent_id="li", session_id="li",
        tool_name=tool_name, tool_args=args or {},
        ts_start_ms=0, ts_end_ms=0,
    )
    return infer_scope(ev) or [f"llama_index.tool.{tool_name}:w"]


def _is_write_call(tool_name: str, args: dict) -> bool:
    ev = AuditEvent(
        trace_id="li", span_id="li", agent_id="li", session_id="li",
        tool_name=tool_name, tool_args=args or {},
        ts_start_ms=0, ts_end_ms=0,
    )
    return is_write(ev)


def _extract_meta(self_tool: Any, args: tuple, kwargs: dict) -> tuple[str, dict]:
    """LlamaIndex FunctionTool.call signature is (*args, **kwargs).
    The tool name lives on .metadata.name. Args = the raw call kwargs;
    if positional args are passed they're folded into _arg0..N."""
    meta = getattr(self_tool, "metadata", None)
    name = getattr(meta, "name", None) or "li_tool"
    tool_args = dict(kwargs) if kwargs else {}
    for i, a in enumerate(args):
        tool_args.setdefault(f"_arg{i}", str(a)[:200] if not isinstance(a, (dict, list, str, int, float, bool)) else a)
    return name, tool_args


def _wrap_acall(original):
    async def wrapper(self, *args, **kwargs):
        tool_name, tool_args = _extract_meta(self, args, kwargs)

        if not _is_write_call(tool_name, tool_args):
            return await original(self, *args, **kwargs)

        scope = _scope_from_call(tool_name, tool_args)
        agent_id = _agent_id_default()

        async with intend(
            scope=scope,
            agent=agent_id,
            session=_session_id(),
            expected_outcome=f"llama_index:{tool_name}",
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


def _wrap_call_sync(original):
    def wrapper(self, *args, **kwargs):
        tool_name, tool_args = _extract_meta(self, args, kwargs)

        if not _is_write_call(tool_name, tool_args):
            return original(self, *args, **kwargs)

        scope = _scope_from_call(tool_name, tool_args)
        agent_id = _agent_id_default()

        async def _run():
            async with intend(
                scope=scope, agent=agent_id, session=_session_id(),
                expected_outcome=f"llama_index:{tool_name}",
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

        # Bridge loop avoids deadlock if call() is reached from inside a
        # running loop (e.g. async ReActAgent → sync tool fallback).
        from synapse.frameworks._sync_bridge import run_coro_blocking
        return run_coro_blocking(_run())

    wrapper.__wrapped__ = original
    return wrapper


def _wrap_call_tool_workflow(original):
    """v0.2.8 fix: patch the Workflow-architecture _call_tool method.

    In llama-index-core>=0.11, ReActAgent.run() / FunctionAgent.run() /
    CodeActAgent.run() / AgentWorkflow.run() all dispatch tools through
    `BaseWorkflowAgent._call_tool(self, ctx, tool, tool_input)`. The old
    `FunctionTool.acall` patch fires too but the workflow path is the
    canonical hook.

    Signature: `async def _call_tool(self, ctx, tool, tool_input) -> ToolOutput`
    """
    async def patched(self, ctx, tool, tool_input):
        tool_name = "unknown_tool"
        try:
            tool_name = tool.metadata.get_name() or "unknown_tool"
        except Exception:
            pass
        # Drop the workflow ctx from the args we hash for scope
        args_for_scope = {k: v for k, v in (tool_input or {}).items()
                         if k not in ("ctx", "context")}
        ev = AuditEvent(
            trace_id="li", span_id="li",
            agent_id=getattr(self, "name", "llama_index_agent"),
            session_id=os.environ.get("SYNAPSE_SESSION_ID", "llama_index_default"),
            tool_name=tool_name, tool_args=args_for_scope or {},
            ts_start_ms=0, ts_end_ms=0,
        )
        if not is_write(ev):
            return await original(self, ctx, tool, tool_input)
        scope = infer_scope(ev) or [f"llama_index.tool.{tool_name}:w"]
        async with intend(
            scope=scope,
            agent=getattr(self, "name", "llama_index_agent"),
            session=os.environ.get("SYNAPSE_SESSION_ID", "llama_index_default"),
            expected_outcome=f"llama_index:{tool_name}",
            blocking=True,
            gate_ms=int(os.environ.get("SYNAPSE_GATE_MS", "200")),
        ) as i:
            try:
                result = await original(self, ctx, tool, tool_input)
                if getattr(result, "is_error", False):
                    i.mark_failed(str(result))
                else:
                    i.set_state_diff({"output_preview": str(result)[:200]})
                return result
            except Exception as e:
                i.mark_failed(str(e))
                raise
    return patched


def _install_llama_index(opts: dict[str, Any]) -> None:
    if _PATCHED["function_tool_call"]:
        return

    try:
        from llama_index.core.tools import FunctionTool  # type: ignore[import-not-found]
    except ImportError:
        try:
            # Older 0.9.x layout
            from llama_index.tools import FunctionTool  # type: ignore[import-not-found]
        except ImportError:
            logger.warning(
                "synapse.install(framework='llama_index'): llama-index-core not installed. "
                "`pip install llama-index-core`."
            )
            return

    if hasattr(FunctionTool, "acall"):
        FunctionTool.acall = _wrap_acall(FunctionTool.acall)
    if hasattr(FunctionTool, "call"):
        FunctionTool.call = _wrap_call_sync(FunctionTool.call)

    # v0.2.8: patch the Workflow-architecture _call_tool hook so ReActAgent.run()
    # in llama-index-core>=0.11 also routes through Synapse.
    try:
        from llama_index.core.agent.workflow.base_agent import BaseWorkflowAgent
        if not getattr(BaseWorkflowAgent._call_tool, "_synapse_wrapped", False):
            BaseWorkflowAgent._call_tool = _wrap_call_tool_workflow(BaseWorkflowAgent._call_tool)
            BaseWorkflowAgent._call_tool._synapse_wrapped = True
            logger.info("synapse.install(framework='llama_index'): patched "
                        "BaseWorkflowAgent._call_tool (covers ReActAgent.run, "
                        "FunctionAgent.run, CodeActAgent.run)")
    except ImportError:
        pass

    try:
        from llama_index.core.agent.workflow.multi_agent_workflow import AgentWorkflow
        if not getattr(AgentWorkflow._call_tool, "_synapse_wrapped", False):
            AgentWorkflow._call_tool = _wrap_call_tool_workflow(AgentWorkflow._call_tool)
            AgentWorkflow._call_tool._synapse_wrapped = True
            logger.info("synapse.install(framework='llama_index'): patched "
                        "AgentWorkflow._call_tool (covers AgentWorkflow.run)")
    except ImportError:
        pass

    _PATCHED["function_tool_call"] = True
    logger.info(
        "synapse.install(framework='llama_index'): patched "
        "FunctionTool.{call,acall} + Workflow._call_tool — every tool call "
        "across every Agent (ReActAgent, FunctionAgent, AgentWorkflow, "
        "legacy OpenAIAgent, FunctionCallingAgent) now participates in "
        "Synapse coordination."
    )


register_framework("llama_index", _install_llama_index)
register_framework("llamaindex", _install_llama_index)
register_framework("llama-index", _install_llama_index)
