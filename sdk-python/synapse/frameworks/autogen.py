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
    """Best-effort agent identity for AutoGen tool calls.

    Resolution order:
      1. ContextVar (synapse.set_agent_context / with_agent) — per-task,
         race-free under asyncio.gather
      2. Best-effort lookup on CancellationToken (rarely populated;
         AutoGen 0.4+ CancellationToken is intentionally transport-only)
      3. SYNAPSE_AGENT_ID env var (legacy)
      4. SYNAPSE_DEFAULT_AGENT_ID env var
      5. "autogen_default"

    Known limitation
    ----------------
    autogen-core's ``FunctionTool.run`` invokes sync user-tool bodies via
    ``loop.run_in_executor(None, partial)`` which does NOT propagate
    contextvars to the worker thread. The wrapper's INTENTION envelope
    is correctly attributed (resolver runs on the caller task), but
    ``synapse.current_agent_id()`` called from inside a sync user-tool
    body running in autogen's executor will see the default. Workaround:
    declare the tool ``async def`` — that path uses ``await self._func()``
    on the caller task and ContextVars propagate naturally.
    """
    from synapse.agent_context import current_agent_id, _AGENT_CTX
    # Check ContextVar first — race-free under concurrent asyncio.gather
    ctx_val = _AGENT_CTX.get()
    if ctx_val:
        return ctx_val
    # Best-effort context attribute walk before falling to env
    if ctx is not None:
        for attr in ("source", "agent_name", "name", "_agent_id"):
            v = getattr(ctx, attr, None)
            if isinstance(v, str) and v:
                return v
    return current_agent_id(default="autogen_default")


def _session_id() -> str:
    return os.environ.get("SYNAPSE_SESSION_ID", "autogen_default_session")


def _wrap_functiontool_run(original):
    """Wrap ``FunctionTool.run`` in AutoGen 0.4+.

    Real signature (verified against autogen-core 0.7.5):
        async def run(self, args: BaseModel, cancellation_token: CancellationToken) -> Any

    We accept *args/**kwargs to be forward-compatible with future SDK
    versions adding optional kwargs (e.g., call_id), then forward
    everything verbatim to the original. Forwarding via *args/**kwargs
    eliminates the double-binding risk from positional/keyword conflict.
    """
    async def wrapper(self, *args, **kwargs):
        # First positional is `args` (pydantic BaseModel); second is
        # `cancellation_token`. Use safe extraction to support either
        # positional OR kwarg call style.
        bm_args = args[0] if len(args) >= 1 else kwargs.get("args")
        cancel_tok = (
            args[1] if len(args) >= 2 else kwargs.get("cancellation_token")
        )

        try:
            tool_args = bm_args.model_dump() if hasattr(bm_args, "model_dump") else dict(bm_args or {})
        except Exception:
            tool_args = {}

        tool_name = getattr(self, "name", None) or type(self).__name__

        if not _is_write_tool(tool_name, tool_args):
            return await original(self, *args, **kwargs)

        scope = _scope_from_call(tool_name, tool_args)
        agent_id = _resolve_agent_id_from_context(cancel_tok)

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
                # Forward args + kwargs verbatim — no double-binding risk.
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
