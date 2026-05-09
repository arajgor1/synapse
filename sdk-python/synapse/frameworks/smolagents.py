"""smolagents adapter for ``synapse.install(framework="smolagents")``.

HuggingFace's smolagents framework: tools subclass ``smolagents.Tool``
and override ``forward()``. We patch ``Tool.__call__`` (which dispatches
to ``forward``) so any tool subclass auto-instruments.

Agent identity for smolagents: the calling agent stores itself in a
threadlocal during tool calls. We read from there if available, else
fall back to the env-default.
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


_PATCHED = {"tool_call": False}


def _session_id() -> str:
    return os.environ.get("SYNAPSE_SESSION_ID", "smolagents_default_session")


def _scope_from_call(tool_name: str, args: dict) -> list[str]:
    ev = AuditEvent(
        trace_id="sa", span_id="sa", agent_id="sa", session_id="sa",
        tool_name=tool_name, tool_args=args or {},
        ts_start_ms=0, ts_end_ms=0,
    )
    return infer_scope(ev) or [f"smolagents.tool.{tool_name}:w"]


def _is_write(tool_name: str, args: dict) -> bool:
    ev = AuditEvent(
        trace_id="sa", span_id="sa", agent_id="sa", session_id="sa",
        tool_name=tool_name, tool_args=args or {},
        ts_start_ms=0, ts_end_ms=0,
    )
    return is_write(ev)


def _agent_id_default() -> str:
    # Per-task ContextVar first (synapse.set_agent_context / with_agent),
    # then SYNAPSE_AGENT_ID env var, then SYNAPSE_DEFAULT_AGENT_ID,
    # then framework-specific fallback.
    from synapse.agent_context import current_agent_id
    return current_agent_id(default="smolagents_agent")


def _wrap_call(original_call):
    """Patch Tool.__call__ — smolagents' synchronous dispatch."""
    import asyncio

    def wrapper(self, *args, **kwargs):
        tool_name = getattr(self, "name", None) or type(self).__name__

        # smolagents tools take **kwargs as the schema; collect them
        tool_args: dict[str, Any] = dict(kwargs)
        if args and not tool_args:
            # Some tools take positional. Fold first positional into a generic key.
            tool_args["_arg0"] = str(args[0])[:200]

        if not _is_write(tool_name, tool_args):
            return original_call(self, *args, **kwargs)

        scope = _scope_from_call(tool_name, tool_args)
        agent_id = _agent_id_default()

        async def _run():
            async with intend(
                scope=scope,
                agent=agent_id,
                session=_session_id(),
                expected_outcome=f"smolagents:{tool_name}",
                blocking=True,
                gate_ms=int(os.environ.get("SYNAPSE_GATE_MS", "200")),
            ) as i:
                try:
                    result = await asyncio.to_thread(original_call, self, *args, **kwargs)
                    i.set_state_diff({"output_preview": str(result)[:200]})
                    return result
                except Exception as e:
                    i.mark_failed(str(e))
                    raise

        # Bridge loop avoids deadlock if Tool.__call__ runs inside a
        # caller's running loop.
        from synapse.frameworks._sync_bridge import run_coro_blocking
        return run_coro_blocking(_run())

    wrapper.__wrapped__ = original_call
    return wrapper


def _install_smolagents(opts: dict[str, Any]) -> None:
    try:
        from smolagents import Tool  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "synapse.install(framework='smolagents'): smolagents not installed. "
            "`pip install smolagents`."
        )
        return

    if _PATCHED["tool_call"]:
        return

    Tool.__call__ = _wrap_call(Tool.__call__)
    _PATCHED["tool_call"] = True
    logger.info("synapse.install(framework='smolagents'): patched Tool.__call__")


register_framework("smolagents", _install_smolagents)
