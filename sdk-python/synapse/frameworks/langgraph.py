"""LangGraph / LangChain adapter for ``synapse.install(framework="langgraph")``.

Hybrid sync+async callback that bridges LangChain tool-call events to
``synapse.intend()``. We pin to the install-time event loop and route
async work onto it via ``run_coroutine_threadsafe`` when the callback
fires on a different loop (LangChain's behavior varies across versions).

Strategy:
  - register a ``BaseCallbackHandler`` (sync) on ``on_tool_start`` /
    ``on_tool_end`` / ``on_tool_error``
  - inside, detect the currently-running loop; if it matches the
    install-time loop, schedule with ``loop.create_task`` (fire-and-forget
    — we drop the synchronous gate but keep INTENTION/RESOLUTION emission)
  - if it doesn't, dispatch to the install-time loop via
    ``run_coroutine_threadsafe`` and block briefly for the result so the
    caller sees conflicts before continuing

If the user wants synchronous gate semantics with full reliability across
LangGraph versions, they can use ``synapse.intend()`` directly inside
their tool handlers — that path is bulletproof.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import os
import time
from typing import Any, Optional

from synapse.intend import _get_agent
from synapse.audit.scope_inference import infer_scope
from synapse.audit.events import AuditEvent, is_write
from synapse.install import register_framework

logger = logging.getLogger(__name__)


def _agent_id_from(metadata: dict, tags: list, parent_run_id) -> str:
    if not metadata:
        metadata = {}
    for k in ("agent_id", "langgraph_node", "agent_name", "graph.node.id"):
        if metadata.get(k):
            return str(metadata[k])
    for t in tags or []:
        if isinstance(t, str) and not t.startswith("seq:") and not t.startswith("graph:"):
            return t
    return "unknown_agent"


def _session_id_from(metadata: dict, run_id) -> str:
    if not metadata:
        metadata = {}
    for k in ("thread_id", "session_id", "conversation_id"):
        if metadata.get(k):
            return str(metadata[k])
    return os.environ.get("SYNAPSE_SESSION_ID", str(run_id) if run_id else "default_session")


def _try_make_handler():
    """Build the callback handler class lazily — only when langchain is installed."""
    try:
        from langchain_core.callbacks import BaseCallbackHandler  # type: ignore[import-not-found]
    except ImportError:
        try:
            from langchain.callbacks.base import BaseCallbackHandler  # type: ignore[import-not-found]
        except ImportError:
            return None

    class SynapseLangGraphCallback(BaseCallbackHandler):
        """Sync-callable handler that schedules async work onto the
        install-time event loop. Compatible with both inline and
        background-thread LangChain callback runners.
        """

        # Mark this as both sync- and async-runnable so LangChain doesn't
        # convert one into the other.
        run_inline = True
        raise_error = False

        def __init__(self, default_session_id: Optional[str] = None) -> None:
            super().__init__()
            self._default_session_id = default_session_id
            # Captured at install time: the loop that owns the bus + state pool
            self._loop: Optional[asyncio.AbstractEventLoop] = None
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                pass
            # run_id -> (intention_id, agent_id, session_id)
            self._active: dict[Any, tuple[str, str, str]] = {}

        # ---- LangChain hooks (sync) ----
        def on_tool_start(
            self,
            serialized: dict,
            input_str: str,
            *,
            run_id,
            parent_run_id=None,
            tags=None,
            metadata=None,
            inputs: Optional[dict] = None,
            **kwargs: Any,
        ) -> None:
            tool_name = (serialized or {}).get("name") or "unknown_tool"
            tool_args = inputs or self._parse_input(input_str)
            agent_id = _agent_id_from(metadata or {}, tags or [], parent_run_id)
            session_id = self._default_session_id or _session_id_from(metadata or {}, run_id)

            ev = AuditEvent(
                trace_id=str(run_id) if run_id else "lc_trace",
                span_id=str(run_id) if run_id else "lc_span",
                agent_id=agent_id,
                session_id=session_id,
                tool_name=tool_name,
                tool_args=tool_args or {},
                ts_start_ms=int(time.time() * 1000),
                ts_end_ms=int(time.time() * 1000),
            )

            if not is_write(ev):
                return

            scope = infer_scope(ev)
            if not scope:
                return

            coro = self._async_emit_intention(
                tool_name, tool_args or {}, scope, agent_id, session_id, run_id,
            )
            self._dispatch_blocking(coro, timeout=2.0)

        def on_tool_end(self, output: Any, *, run_id, **kwargs: Any) -> None:
            entry = self._active.pop(run_id, None)
            if entry is None:
                return
            intention_id, agent_id, session_id = entry
            coro = self._async_emit_resolution(
                intention_id, agent_id, session_id,
                outcome="success",
                state_diff={"output_preview": str(output)[:200]},
            )
            self._dispatch_fire_and_forget(coro)

        def on_tool_error(self, error: BaseException, *, run_id, **kwargs: Any) -> None:
            entry = self._active.pop(run_id, None)
            if entry is None:
                return
            intention_id, agent_id, session_id = entry
            coro = self._async_emit_resolution(
                intention_id, agent_id, session_id,
                outcome="failure",
                state_diff={"error": str(error)[:200]},
            )
            self._dispatch_fire_and_forget(coro)

        # ---- Async helpers that run on the bus loop ----
        async def _async_emit_intention(
            self, tool_name, tool_args, scope, agent_id, session_id, run_id,
        ) -> Optional[tuple[str, list]]:
            try:
                syn_agent = await _get_agent(agent_id, session_id)
            except Exception as e:
                logger.warning("synapse.langgraph: _get_agent failed (%s)", e)
                return None
            if syn_agent is None:
                return None

            try:
                intention_id, conflicts = await syn_agent.emit_intention(
                    action={"tool": tool_name, "args": tool_args},
                    scope=scope,
                    expected_outcome=f"langgraph:{tool_name}",
                    blocking=True,
                    gate_ms=int(os.environ.get("SYNAPSE_GATE_MS", "200")),
                )
                if conflicts:
                    logger.warning(
                        "synapse.langgraph: CONFLICT on tool=%s scope=%s "
                        "agent=%s — %d conflicting intention(s)",
                        tool_name, scope, agent_id, len(conflicts),
                    )
                self._active[run_id] = (intention_id, agent_id, session_id)
                return intention_id, conflicts
            except Exception as e:
                logger.warning("synapse.langgraph: emit_intention failed (%s)", e)
                return None

        async def _async_emit_resolution(
            self, intention_id, agent_id, session_id, *, outcome, state_diff,
        ) -> None:
            try:
                syn_agent = await _get_agent(agent_id, session_id)
                if syn_agent is None:
                    return
                await syn_agent.emit_resolution(
                    intention_id=intention_id,
                    outcome=outcome,
                    state_diff=state_diff,
                )
            except Exception as e:
                logger.warning("synapse.langgraph: emit_resolution failed (%s)", e)

        # ---- Loop dispatch ----
        def _dispatch_blocking(self, coro, *, timeout: float) -> Any:
            """Run coro on the install-time loop and wait for it.

            If we're on the install-time loop already (rare with LangChain
            background callbacks but possible), can't block — fall back to
            create_task and lose the synchronous gate.
            """
            install_loop = self._loop
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None

            if install_loop is None or running is install_loop:
                # Same loop — schedule and continue (no synchronous gate)
                if running is not None:
                    running.create_task(coro)
                else:
                    # Last resort: run synchronously
                    asyncio.run(coro)
                return None

            # Different loop / no loop in this thread — bridge via threadsafe
            try:
                fut = asyncio.run_coroutine_threadsafe(coro, install_loop)
                return fut.result(timeout=timeout)
            except Exception as e:
                logger.warning("synapse.langgraph: dispatch failed (%s)", e)
                return None

        def _dispatch_fire_and_forget(self, coro) -> None:
            """Schedule coro on the install-time loop without blocking."""
            install_loop = self._loop
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None

            if install_loop is not None and running is not install_loop:
                try:
                    asyncio.run_coroutine_threadsafe(coro, install_loop)
                    return
                except Exception:
                    pass
            if running is not None:
                running.create_task(coro)

        @staticmethod
        def _parse_input(input_str: Any) -> dict:
            import json
            if isinstance(input_str, dict):
                return input_str
            if isinstance(input_str, str):
                s = input_str.strip()
                if s.startswith("{"):
                    try:
                        return json.loads(s)
                    except Exception:
                        pass
            return {}

    return SynapseLangGraphCallback


# ---------------------------------------------------------------------------
# Module-level handle
# ---------------------------------------------------------------------------
_handler_singleton: Any = None


def get_callback() -> Optional[Any]:
    """Return the SynapseLangGraphCallback instance (after install)."""
    return _handler_singleton


def _install_langgraph(opts: dict[str, Any]) -> None:
    global _handler_singleton

    Cls = _try_make_handler()
    if Cls is None:
        logger.warning(
            "synapse.install(framework='langgraph'): langchain-core not installed. "
            "`pip install langchain-core langgraph`. Falling back to manual "
            "synapse.intend()."
        )
        return

    handler = Cls(default_session_id=opts.get("session_id"))
    _handler_singleton = handler

    logger.info(
        "synapse.install(framework='langgraph'): callback ready. "
        "Attach via graph.invoke(input, config={'callbacks':[synapse.frameworks.langgraph.get_callback()]}) "
        "for explicit control, or rely on LangChain's global callback manager "
        "when configured."
    )


# Self-register on import
register_framework("langgraph", _install_langgraph)
