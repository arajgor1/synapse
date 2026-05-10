"""Generic OpenTelemetry-live adapter for ``synapse.install(framework="otel")``.

Works against ANY agent framework that emits OpenTelemetry tool-call spans.
That includes (as of 2026):
  * Vercel AI SDK
  * CopilotKit / AssistantKit
  * Inngest agents
  * Langroid
  * Anthropic Computer Use SDK
  * Anything that follows the OpenInference or OpenTelemetry GenAI
    semantic conventions (https://opentelemetry.io/docs/specs/semconv/gen-ai/)

How it works
------------
On install, we register a Synapse SpanProcessor with the global
TracerProvider. The processor inspects every span's ``on_end`` event:

  1. If the span is a tool-call (detected via OpenInference's
     ``openinference.span.kind == "TOOL"`` OR OTel GenAI's
     ``gen_ai.operation.name == "execute_tool"`` OR ``mcp.tool.name``),
     we emit a Synapse INTENTION + RESOLUTION pair after-the-fact.
  2. Tool name + args are extracted from standard span attributes
     (``tool.name`` / ``gen_ai.tool.name`` / ``mcp.tool.name``;
     ``tool.parameters`` / ``gen_ai.tool.call.arguments``).
  3. Agent identity comes from ``gen_ai.agent.name`` if present, else
     the synapse ContextVar (``set_agent_context``), else the standard
     fallback chain.

This is a POST-HOC instrumentation path: we record the intent AFTER
the tool has already run (because we see the span on close). It catches
silent collisions for audit / dashboards but cannot block-and-pivot
the way the dispatch-level adapters can. For pre-execution gating,
use a framework-specific adapter when one exists.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Optional

from synapse.audit.events import AuditEvent, is_write
from synapse.audit.scope_inference import infer_scope
from synapse.install import register_framework

logger = logging.getLogger(__name__)


_PATCHED = {"otel": False}


# Span attribute keys we look for, in priority order.
TOOL_NAME_ATTRS = (
    "tool.name",
    "gen_ai.tool.name",
    "mcp.tool.name",
    "openinference.tool.name",
)
TOOL_ARGS_ATTRS = (
    "tool.parameters",
    "tool.input",
    "gen_ai.tool.call.arguments",
    "input.value",
)
AGENT_NAME_ATTRS = (
    "gen_ai.agent.name",
    "agent.name",
    "openinference.agent.name",
)
TOOL_KIND_ATTRS = (
    ("openinference.span.kind", "TOOL"),
    ("openinference.span.kind", "tool"),
    ("gen_ai.operation.name", "execute_tool"),
)


def _is_tool_span(attrs: dict) -> bool:
    """True if the span looks like a tool invocation."""
    for k, v in TOOL_KIND_ATTRS:
        if attrs.get(k) == v:
            return True
    # Heuristic fallback: a name attr + an args attr is enough.
    if any(k in attrs for k in TOOL_NAME_ATTRS) and any(k in attrs for k in TOOL_ARGS_ATTRS):
        return True
    return False


def _first_attr(attrs: dict, keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in attrs:
            return attrs[k]
    return None


def _coerce_args(raw: Any) -> dict:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            import json
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        return {"_input": raw[:500]}
    if raw is None:
        return {}
    return {"_arg": str(raw)[:200]}


def _resolve_agent_id(span_attrs: dict) -> str:
    """Span-attribute agent name > ContextVar > env > default."""
    from synapse.agent_context import current_agent_id, _AGENT_CTX
    ctx_val = _AGENT_CTX.get()
    if ctx_val:
        return ctx_val
    span_val = _first_attr(span_attrs, AGENT_NAME_ATTRS)
    if isinstance(span_val, str) and span_val:
        return span_val
    return current_agent_id(default="otel_agent")


def _make_processor():
    """Build the SynapseOTelSpanProcessor class. Lazy import of OTel
    SDK keeps base install (no OTel) cheap."""
    from opentelemetry.sdk.trace import SpanProcessor

    class SynapseOTelSpanProcessor(SpanProcessor):
        """Observes every closed span; emits a Synapse INTENTION +
        RESOLUTION pair if the span is a tool invocation."""

        def __init__(self, session_id: Optional[str] = None) -> None:
            self._session_id = session_id
            self._loop: Optional[asyncio.AbstractEventLoop] = None
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                pass  # set lazily on first end()

        def on_start(self, span, parent_context=None) -> None:  # noqa: D401
            return None

        def on_end(self, span) -> None:
            # Diagnostic: log every span we see (one line per span).
            # SYNAPSE_OTEL_DEBUG=1 enables; off by default to avoid noise.
            debug = os.environ.get("SYNAPSE_OTEL_DEBUG") == "1"
            if debug:
                # Unconditional first line — proves on_end is being
                # invoked at all (separates "processor not registered"
                # from "processor registered but conditional skipped").
                print(
                    f"[synapse.otel] >> on_end ENTERED span_name={span.name} "
                    f"context={getattr(span, 'context', None)}",
                    flush=True,
                )
            try:
                attrs = dict(span.attributes or {})
            except Exception:
                if debug:
                    print(f"[synapse.otel] on_end: bad attrs on span={span.name}", flush=True)
                return
            if debug:
                print(
                    f"[synapse.otel] on_end span_name={span.name} "
                    f"attr_count={len(attrs)} "
                    f"tool_name_attr={_first_attr(attrs, TOOL_NAME_ATTRS)} "
                    f"kind_attr={attrs.get('openinference.span.kind') or attrs.get('gen_ai.operation.name')}",
                    flush=True,
                )
            if not _is_tool_span(attrs):
                if debug:
                    print(f"[synapse.otel]   -> skipped (not_tool_span)", flush=True)
                return

            tool_name = str(_first_attr(attrs, TOOL_NAME_ATTRS) or span.name or "otel_tool")
            tool_args = _coerce_args(_first_attr(attrs, TOOL_ARGS_ATTRS))

            # Cheap no-op: skip read-only tool kinds (the audit pipeline
            # already filters; we mirror that here so the bus doesn't
            # carry weight from `web.search` / `vector.search` / etc.).
            ev = AuditEvent(
                trace_id="otel", span_id="otel", agent_id="otel", session_id="otel",
                tool_name=tool_name, tool_args=tool_args,
                ts_start_ms=0, ts_end_ms=0,
            )
            if not is_write(ev):
                if debug:
                    print(f"[synapse.otel]   -> skipped (not_write tool={tool_name})", flush=True)
                return

            scope = infer_scope(ev) or [f"otel.tool.{tool_name}:w"]
            agent_id = _resolve_agent_id(attrs)
            session_id = (
                self._session_id
                or os.environ.get("SYNAPSE_SESSION_ID")
                or "otel_default_session"
            )

            async def _emit() -> None:
                # Defer the intend() import to avoid eager-loading the
                # bus at install time.
                from synapse.intend import intend
                async with intend(
                    scope=scope,
                    agent=agent_id,
                    session=session_id,
                    expected_outcome=f"otel:{tool_name}",
                    blocking=False,  # post-hoc — can't block; just record
                    gate_ms=0,
                ) as i:
                    try:
                        # Capture span output if the framework attaches it
                        out = (
                            attrs.get("output.value")
                            or attrs.get("gen_ai.tool.call.result")
                            or ""
                        )
                        i.set_state_diff({"output_preview": str(out)[:200]})
                    except Exception:
                        pass

            # Schedule onto a usable loop. on_end fires from the OTel
            # exporter thread, which has no running loop — use the
            # sync_bridge to route.
            try:
                from synapse.frameworks._sync_bridge import run_coro_blocking
                if debug:
                    print(f"[synapse.otel]   -> emitting intent scope={scope} agent={agent_id} session={session_id}", flush=True)
                run_coro_blocking(_emit())
                if debug:
                    print(f"[synapse.otel]   -> emit returned ok", flush=True)
            except Exception as e:
                if debug:
                    print(f"[synapse.otel]   -> emit FAILED: {type(e).__name__}: {e}", flush=True)
                logger.warning("synapse.otel: emit failed for %s (%s)", tool_name, e)

        def shutdown(self) -> None:
            return None

        def force_flush(self, timeout_millis: int = 30000) -> bool:  # noqa: D401
            return True

    return SynapseOTelSpanProcessor


def _install_otel(opts: dict[str, Any]) -> None:
    """Register the SynapseOTelSpanProcessor on the current global
    TracerProvider.

    Idempotent in the sense that it's safe to call multiple times — but
    NOT short-circuiting on _PATCHED, because libraries imported later
    (autogen-ext, openai-agents, google-adk) sometimes replace the
    global TracerProvider after our install. Calling install() again
    re-attaches the SpanProcessor to whatever provider is current.
    Each registration is tracked by id(provider) so we don't double-add
    to the same provider.
    """
    try:
        from opentelemetry import trace as otel_trace
        from opentelemetry.sdk.trace import TracerProvider
    except ImportError:
        logger.warning(
            "synapse.install(framework='otel'): opentelemetry-sdk not installed. "
            "`pip install opentelemetry-sdk`."
        )
        return

    provider = otel_trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        # Default global provider isn't a real SDK provider — set one up.
        provider = TracerProvider()
        otel_trace.set_tracer_provider(provider)
        logger.info("synapse.install(framework='otel'): installed default TracerProvider")

    seen = _PATCHED.setdefault("otel_provider_ids", set())
    pid = id(provider)
    if pid in seen:
        logger.debug(
            "synapse.install(framework='otel'): SpanProcessor already on this "
            "TracerProvider (id=%s); skipping duplicate registration.", pid,
        )
        return

    proc_cls = _make_processor()
    processor = proc_cls(session_id=opts.get("session_id"))
    provider.add_span_processor(processor)
    seen.add(pid)
    _PATCHED["otel"] = True
    logger.info(
        "synapse.install(framework='otel'): registered SynapseOTelSpanProcessor "
        "on TracerProvider id=%s (n_attached=%d). Every closed tool span "
        "(OpenInference / OTel GenAI / MCP) now emits a Synapse INTENTION post-hoc.",
        pid, len(seen),
    )


register_framework("otel", _install_otel)
register_framework("opentelemetry", _install_otel)
register_framework("otel_live", _install_otel)
