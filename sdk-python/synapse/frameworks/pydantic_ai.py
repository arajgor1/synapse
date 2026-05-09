"""Pydantic AI adapter for ``synapse.install(framework="pydantic_ai")``.

In Pydantic AI 1.0+ the dispatch entry point is
``pydantic_ai.toolsets.AbstractToolset.call_tool(name, tool_args, ctx, tool)``
— a coroutine that every concrete toolset (FunctionToolset, AgentToolset,
PrefixedToolset, etc.) inherits or overrides. Patching at the abstract
base catches every concrete subclass automatically.

The pre-1.0 ``Tool.run`` / ``Tool.call`` methods that earlier versions of
this adapter probed for no longer exist in 1.0+; the previous adapter
silently no-op'd against any modern install.

Agent identity comes from ``ctx.agent.name`` when set, falling back to
SYNAPSE_AGENT_ID env var, then SYNAPSE_DEFAULT_AGENT_ID.
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


_PATCHED = {"call_tool": False}


def _session_id() -> str:
    return os.environ.get("SYNAPSE_SESSION_ID", "pydantic_ai_default_session")


def _agent_name_from_runcontext(ctx: Any) -> str:
    """Walk the RunContext object graph for an agent identity.

    Resolution order (race-free under asyncio.gather):
      1. ContextVar (synapse.set_agent_context / with_agent) — per-task
      2. RunContext.agent.name (or other walked paths) — framework-supplied
      3. SYNAPSE_AGENT_ID env var (legacy)
      4. SYNAPSE_DEFAULT_AGENT_ID env var
      5. "pydantic_ai_agent"
    """
    from synapse.agent_context import current_agent_id, _AGENT_CTX
    # ContextVar wins — race-free under concurrent asyncio.gather
    ctx_val = _AGENT_CTX.get()
    if ctx_val:
        return ctx_val
    if ctx is not None:
        for path in (("agent", "name"), ("name",), ("deps", "name"), ("agent", "_name")):
            cur = ctx
            for attr in path:
                cur = getattr(cur, attr, None)
                if cur is None:
                    break
            if isinstance(cur, str) and cur:
                return cur
    return current_agent_id(default="pydantic_ai_agent")


def _scope_from_call(tool_name: str, args: dict) -> list[str]:
    ev = AuditEvent(
        trace_id="pa", span_id="pa", agent_id="pa", session_id="pa",
        tool_name=tool_name, tool_args=args or {},
        ts_start_ms=0, ts_end_ms=0,
    )
    return infer_scope(ev) or [f"pydantic_ai.tool.{tool_name}:w"]


def _is_write_call(tool_name: str, args: dict) -> bool:
    ev = AuditEvent(
        trace_id="pa", span_id="pa", agent_id="pa", session_id="pa",
        tool_name=tool_name, tool_args=args or {},
        ts_start_ms=0, ts_end_ms=0,
    )
    return is_write(ev)


def _coerce_args(args: Any) -> dict:
    """Normalize the `tool_args` parameter shape across pydantic_ai versions."""
    if args is None:
        return {}
    if isinstance(args, dict):
        return dict(args)
    if hasattr(args, "model_dump"):
        try:
            return args.model_dump()
        except Exception:
            return {}
    if isinstance(args, (list, tuple)):
        # Best-effort flatten; rare path
        return {"_args": list(args)[:10]}
    return {"_arg": str(args)[:200]}


def _wrap_call_tool(original):
    """Wrap AbstractToolset.call_tool — the canonical 1.0+ entry point.

    Real signature: `async def call_tool(self, name, tool_args, ctx, tool)`.
    """

    async def wrapper(self, name, tool_args, ctx, tool, *more, **kwargs):
        coerced_args = _coerce_args(tool_args)

        if not _is_write_call(name, coerced_args):
            return await original(self, name, tool_args, ctx, tool, *more, **kwargs)

        scope = _scope_from_call(name, coerced_args)
        agent_id = _agent_name_from_runcontext(ctx)

        async with intend(
            scope=scope,
            agent=agent_id,
            session=_session_id(),
            expected_outcome=f"pydantic_ai:{name}",
            blocking=True,
            gate_ms=int(os.environ.get("SYNAPSE_GATE_MS", "200")),
        ) as i:
            try:
                result = await original(self, name, tool_args, ctx, tool, *more, **kwargs)
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


def _install_pydantic_ai(opts: dict[str, Any]) -> None:
    if _PATCHED["call_tool"]:
        return

    # Pydantic AI 1.0+ canonical path
    try:
        from pydantic_ai.toolsets import AbstractToolset  # type: ignore[import-not-found]
    except ImportError:
        # Fall back to legacy Tool.run/call probe for very old versions
        try:
            from pydantic_ai.tools import Tool  # type: ignore[import-not-found]
            for attr in ("run", "call", "execute", "_run"):
                original = getattr(Tool, attr, None)
                if original and callable(original):
                    setattr(Tool, attr, _wrap_call_tool(original))
                    _PATCHED["call_tool"] = True
                    logger.info(
                        "synapse.install(framework='pydantic_ai'): patched legacy Tool.%s",
                        attr,
                    )
                    return
        except ImportError:
            pass
        logger.warning(
            "synapse.install(framework='pydantic_ai'): pydantic-ai not installed, "
            "or version too old/new for known dispatch paths. "
            "`pip install pydantic-ai` (>=1.0)."
        )
        return

    # Patch the abstract base — every concrete subclass inherits this.
    AbstractToolset.call_tool = _wrap_call_tool(AbstractToolset.call_tool)
    _PATCHED["call_tool"] = True
    logger.info(
        "synapse.install(framework='pydantic_ai'): patched "
        "pydantic_ai.toolsets.AbstractToolset.call_tool"
    )


register_framework("pydantic_ai", _install_pydantic_ai)
register_framework("pydantic-ai", _install_pydantic_ai)
