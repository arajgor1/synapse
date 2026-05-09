"""Google ADK adapter for ``synapse.install(framework="google_adk")``.

Google's Agent Development Kit (ADK) — the open-source SDK behind
Vertex AI Agent Builder — dispatches every tool call through
``google.adk.tools.BaseTool.run_async(*, args, tool_context)``.

Patching at the abstract base catches every concrete subclass:
FunctionTool, AgentTool, MCPToolset, APIHubToolset, ExampleTool,
LongRunningFunctionTool, DiscoveryEngineSearchTool, etc.

Verified against google-adk (latest). All ADK tool subclasses inherit
the same `run_async` keyword-only signature, so a single patch covers
the entire framework.

We deliberately ship this BEFORE Semantica's "coming soon" Google ADK
integration. ADK + Vertex Agent Builder is the fastest-growing
enterprise-cloud agent stack and Synapse already supports the Vertex
trace format on the audit side; this adapter completes the live path.
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


_PATCHED = {"basetool_run_async": False}


def _session_id() -> str:
    return os.environ.get("SYNAPSE_SESSION_ID", "google_adk_default_session")


def _agent_id_from_context(ctx: Any) -> str:
    """ADK ToolContext exposes the InvocationContext + agent identity.

    Resolution order (race-free under asyncio.gather):
      1. ContextVar (synapse.set_agent_context / with_agent) — per-task
      2. ToolContext.invocation_context.agent.name (or other walked paths)
      3. SYNAPSE_AGENT_ID env var (legacy)
      4. SYNAPSE_DEFAULT_AGENT_ID env var
      5. "google_adk_agent"
    """
    from synapse.agent_context import current_agent_id, _AGENT_CTX
    # ContextVar wins — race-free under concurrent asyncio.gather
    ctx_val = _AGENT_CTX.get()
    if ctx_val:
        return ctx_val
    if ctx is not None:
        # ToolContext typically has .invocation_context.agent.name
        for path in (
            ("invocation_context", "agent", "name"),
            ("agent", "name"),
            ("name",),
            ("invocation_context", "session_id"),
        ):
            cur = ctx
            for attr in path:
                cur = getattr(cur, attr, None)
                if cur is None:
                    break
            if isinstance(cur, str) and cur:
                return cur
    return current_agent_id(default="google_adk_agent")


def _scope_from_call(tool_name: str, args: dict) -> list[str]:
    ev = AuditEvent(
        trace_id="adk", span_id="adk", agent_id="adk", session_id="adk",
        tool_name=tool_name, tool_args=args or {},
        ts_start_ms=0, ts_end_ms=0,
    )
    return infer_scope(ev) or [f"google_adk.tool.{tool_name}:w"]


def _is_write_call(tool_name: str, args: dict) -> bool:
    ev = AuditEvent(
        trace_id="adk", span_id="adk", agent_id="adk", session_id="adk",
        tool_name=tool_name, tool_args=args or {},
        ts_start_ms=0, ts_end_ms=0,
    )
    return is_write(ev)


def _wrap_run_async(original):
    """Wrap BaseTool.run_async — keyword-only signature
    `(self, *, args: dict[str, Any], tool_context: ToolContext)`.
    """

    async def wrapper(self, *, args, tool_context, **extra_kwargs):
        tool_name = getattr(self, "name", None) or type(self).__name__
        tool_args = dict(args) if args else {}

        if not _is_write_call(tool_name, tool_args):
            return await original(self, args=args, tool_context=tool_context, **extra_kwargs)

        scope = _scope_from_call(tool_name, tool_args)
        agent_id = _agent_id_from_context(tool_context)

        async with intend(
            scope=scope,
            agent=agent_id,
            session=_session_id(),
            expected_outcome=f"google_adk:{tool_name}",
            blocking=True,
            gate_ms=int(os.environ.get("SYNAPSE_GATE_MS", "200")),
        ) as i:
            try:
                result = await original(
                    self, args=args, tool_context=tool_context, **extra_kwargs
                )
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


def _install_google_adk(opts: dict[str, Any]) -> None:
    if _PATCHED["basetool_run_async"]:
        return

    try:
        from google.adk.tools import BaseTool  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "synapse.install(framework='google_adk'): google-adk not installed. "
            "`pip install google-adk`."
        )
        return

    BaseTool.run_async = _wrap_run_async(BaseTool.run_async)
    _PATCHED["basetool_run_async"] = True
    logger.info(
        "synapse.install(framework='google_adk'): patched "
        "google.adk.tools.BaseTool.run_async — every tool call across every "
        "ADK Agent (Llm, Loop, Parallel, Sequential) and every concrete tool "
        "subclass (FunctionTool, AgentTool, MCPToolset, APIHubToolset, ...) "
        "now participates in Synapse coordination."
    )


register_framework("google_adk", _install_google_adk)
register_framework("google-adk", _install_google_adk)
register_framework("adk", _install_google_adk)
