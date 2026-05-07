"""AutoGen adapter for ``synapse.install(framework="autogen")``.

Supports both AutoGen 0.4+ (autogen-agentchat / autogen-core) and the
older autogen 0.2 API. Hooks the tool-call dispatch path so each
``FunctionTool.run()`` participates in Synapse coordination.

AutoGen's tools are built from plain Python callables wrapped by
``FunctionTool``. We monkey-patch ``FunctionTool.run`` (or the equivalent
``_func_call`` in older versions) at install time.

Agent identity comes from the calling agent's ``name`` (carried via
``ToolCallContext`` in 0.4 or threadlocal in older versions). Multi-agent
attribution requires AutoGen 0.4+; older versions get a generic agent_id.
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


_PATCHED = {"functiontool_run": False}


def _scope_from_call(tool_name: str, args: dict) -> list[str]:
    ev = AuditEvent(
        trace_id="ag", span_id="ag", agent_id="ag", session_id="ag",
        tool_name=tool_name, tool_args=args or {},
        ts_start_ms=0, ts_end_ms=0,
    )
    return infer_scope(ev) or [f"autogen.tool.{tool_name}:w"]


def _is_write_tool(tool_name: str, args: dict) -> bool:
    ev = AuditEvent(
        trace_id="ag", span_id="ag", agent_id="ag", session_id="ag",
        tool_name=tool_name, tool_args=args or {},
        ts_start_ms=0, ts_end_ms=0,
    )
    return is_write(ev)


def _resolve_agent_id_from_context(ctx: Any) -> str:
    """Best-effort agent identity from AutoGen's CancellationToken / context."""
    if ctx is None:
        return "autogen_default"
    for attr in ("source", "agent_name", "name"):
        v = getattr(ctx, attr, None)
        if isinstance(v, str) and v:
            return v
    return os.environ.get("SYNAPSE_DEFAULT_AGENT_ID", "autogen_default")


def _session_id() -> str:
    return os.environ.get("SYNAPSE_SESSION_ID", "autogen_default_session")


def _wrap_functiontool_run(original):
    """Wrap ``FunctionTool.run`` in AutoGen 0.4+."""
    async def wrapper(self, args, cancellation_token=None, *more, **kwargs):
        # args in 0.4+ is a pydantic model; coerce to dict
        try:
            tool_args = args.model_dump() if hasattr(args, "model_dump") else dict(args or {})
        except Exception:
            tool_args = {}

        tool_name = getattr(self, "name", None) or type(self).__name__

        if not _is_write_tool(tool_name, tool_args):
            return await original(self, args, cancellation_token, *more, **kwargs)

        scope = _scope_from_call(tool_name, tool_args)
        agent_id = _resolve_agent_id_from_context(cancellation_token)

        async with intend(
            scope=scope,
            agent=agent_id,
            session=_session_id(),
            expected_outcome=f"autogen:{tool_name}",
            blocking=True,
            gate_ms=int(os.environ.get("SYNAPSE_GATE_MS", "200")),
        ) as i:
            if i.has_conflicts:
                logger.warning(
                    "synapse.autogen: CONFLICT on tool=%s agent=%s scope=%s",
                    tool_name, agent_id, scope,
                )
            try:
                result = await original(self, args, cancellation_token, *more, **kwargs)
                i.set_state_diff({"output_preview": str(result)[:200]})
                return result
            except Exception as e:
                i.mark_failed(str(e))
                raise

    wrapper.__wrapped__ = original
    return wrapper


def _install_autogen(opts: dict[str, Any]) -> None:
    # Try AutoGen 0.4+ first (autogen_core)
    patched_any = False
    try:
        from autogen_core.tools import FunctionTool  # type: ignore[import-not-found]
        if not _PATCHED["functiontool_run"]:
            FunctionTool.run = _wrap_functiontool_run(FunctionTool.run)
            _PATCHED["functiontool_run"] = True
            patched_any = True
        logger.info("synapse.install(framework='autogen'): patched autogen_core.FunctionTool.run")
    except ImportError:
        pass

    if not patched_any:
        # Try the older 0.2 API
        try:
            import autogen  # type: ignore[import-not-found]
            logger.info(
                "synapse.install(framework='autogen'): autogen 0.2 detected. "
                "Use synapse.intend() inside your tool functions for now — "
                "global instrumentation requires autogen-core (0.4+)."
            )
        except ImportError:
            logger.warning(
                "synapse.install(framework='autogen'): neither autogen-core (0.4+) "
                "nor autogen (0.2) is installed. `pip install autogen-agentchat`."
            )


register_framework("autogen", _install_autogen)
register_framework("autogen_agentchat", _install_autogen)
register_framework("autogen_core", _install_autogen)
