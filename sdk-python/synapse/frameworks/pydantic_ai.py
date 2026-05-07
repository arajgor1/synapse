"""Pydantic AI adapter for ``synapse.install(framework="pydantic_ai")``.

Pydantic AI's ``Agent`` exposes ``@agent.tool`` and ``@agent.tool_plain``
decorators that turn Python functions into agent-callable tools. We
intercept by patching the ``Tool`` class's ``run`` (or ``call``) method
at install time.

Agent identity comes from the calling Agent's ``name`` attribute (set
via ``Agent(name="...")``).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from synapse.intend import intend
from synapse.audit.events import AuditEvent, is_write
from synapse.audit.scope_inference import infer_scope
from synapse.install import register_framework

logger = logging.getLogger(__name__)


_PATCHED = {"tool_run": False}


def _session_id() -> str:
    return os.environ.get("SYNAPSE_SESSION_ID", "pydantic_ai_default_session")


def _agent_name_from_runcontext(ctx: Any) -> str:
    if ctx is None:
        return os.environ.get("SYNAPSE_DEFAULT_AGENT_ID", "pydantic_ai_agent")
    # RunContext exposes the deps + the running agent
    for path in (("agent", "name"), ("name",), ("deps", "name")):
        cur = ctx
        for attr in path:
            cur = getattr(cur, attr, None)
            if cur is None:
                break
        if isinstance(cur, str) and cur:
            return cur
    return os.environ.get("SYNAPSE_DEFAULT_AGENT_ID", "pydantic_ai_agent")


def _scope_from_call(tool_name: str, args: dict) -> list[str]:
    ev = AuditEvent(
        trace_id="pa", span_id="pa", agent_id="pa", session_id="pa",
        tool_name=tool_name, tool_args=args or {},
        ts_start_ms=0, ts_end_ms=0,
    )
    return infer_scope(ev) or [f"pydantic_ai.tool.{tool_name}:w"]


def _is_write(tool_name: str, args: dict) -> bool:
    ev = AuditEvent(
        trace_id="pa", span_id="pa", agent_id="pa", session_id="pa",
        tool_name=tool_name, tool_args=args or {},
        ts_start_ms=0, ts_end_ms=0,
    )
    return is_write(ev)


def _wrap_tool_run(original):
    async def wrapper(self, ctx, args=None, *more, **kwargs):
        tool_name = getattr(self, "name", None) or getattr(self, "function_name", None) or "tool"
        tool_args = {}
        if isinstance(args, dict):
            tool_args = dict(args)
        elif hasattr(args, "model_dump"):
            tool_args = args.model_dump()

        if not _is_write(tool_name, tool_args):
            return await original(self, ctx, args, *more, **kwargs)

        scope = _scope_from_call(tool_name, tool_args)
        agent_id = _agent_name_from_runcontext(ctx)

        async with intend(
            scope=scope,
            agent=agent_id,
            session=_session_id(),
            expected_outcome=f"pydantic_ai:{tool_name}",
            blocking=True,
            gate_ms=int(os.environ.get("SYNAPSE_GATE_MS", "200")),
        ) as i:
            try:
                result = await original(self, ctx, args, *more, **kwargs)
                i.set_state_diff({"output_preview": str(result)[:200]})
                return result
            except Exception as e:
                i.mark_failed(str(e))
                raise

    wrapper.__wrapped__ = original
    return wrapper


def _install_pydantic_ai(opts: dict[str, Any]) -> None:
    try:
        from pydantic_ai.tools import Tool  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "synapse.install(framework='pydantic_ai'): pydantic-ai not installed. "
            "`pip install pydantic-ai`."
        )
        return

    # Find the run / call / async-invoke method. Pydantic AI has used
    # different names across releases.
    for attr in ("run", "call", "execute", "_run"):
        original = getattr(Tool, attr, None)
        if original and callable(original) and not _PATCHED["tool_run"]:
            try:
                setattr(Tool, attr, _wrap_tool_run(original))
                _PATCHED["tool_run"] = True
                logger.info(
                    "synapse.install(framework='pydantic_ai'): patched Tool.%s", attr
                )
                return
            except Exception as e:
                logger.warning("synapse.pydantic_ai: failed to patch Tool.%s (%s)", attr, e)

    logger.warning(
        "synapse.install(framework='pydantic_ai'): could not find Tool.run/call to patch. "
        "Use synapse.intend() manually."
    )


register_framework("pydantic_ai", _install_pydantic_ai)
register_framework("pydantic-ai", _install_pydantic_ai)
