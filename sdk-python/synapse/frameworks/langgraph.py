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
            # Captured at install time: the loop that owns the bus + state pool.
            # Use get_running_loop() — get_event_loop() is deprecated in 3.12+
            # when no loop is running.
            self._loop: Optional[asyncio.AbstractEventLoop] = None
            try:
                self._loop = asyncio.get_running_loop()
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


_RUNNABLE_PATCHED = False
_CONFIGURE_HOOK_TOKEN: Any = None


def _register_via_configure_hook(handler: Any) -> bool:
    """v0.2.6: register our handler via LangChain's
    ``langchain_core.tracers.context.register_configure_hook``. This is the
    canonical mechanism for "inject this callback into every Runnable's
    config" and propagates correctly into nested graphs (StateGraph nodes,
    ToolNode dispatches, etc.) where simple top-level config injection
    doesn't reach.

    Returns True if the hook was registered.
    """
    global _CONFIGURE_HOOK_TOKEN
    if _CONFIGURE_HOOK_TOKEN is not None:
        return True
    try:
        from langchain_core.tracers.context import register_configure_hook
        from contextvars import ContextVar
    except ImportError:
        return False

    # Create a ContextVar that always yields our handler. register_configure_hook
    # accepts a ContextVar AND will read its value when building each Runnable's
    # config. Setting a default value ensures the handler is always present.
    handler_cv: ContextVar = ContextVar("synapse_langgraph_handler", default=handler)
    try:
        register_configure_hook(
            handler_cv,
            inheritable=True,  # propagates to child Runnables (ToolNode etc.)
        )
        _CONFIGURE_HOOK_TOKEN = handler_cv
        logger.info(
            "synapse.install(framework='langgraph'): registered handler via "
            "langchain_core.tracers.context.register_configure_hook "
            "(inheritable=True). Nested Runnables in create_react_agent "
            "/ ToolNode dispatch paths will now see the handler."
        )
        return True
    except Exception as e:
        logger.warning("synapse.install(framework='langgraph'): "
                       "register_configure_hook failed (%s)", e)
        return False


def _auto_attach_handler_to_runnable(handler: Any) -> bool:
    """v0.2.6 fix (Phase 7b regression): monkey-patch
    ``langchain_core.runnables.base.Runnable.ainvoke / .invoke / .astream / .stream``
    so every Runnable execution automatically gets our handler in
    ``config["callbacks"]``.

    Previously the adapter ONLY created the callback handler and required
    users to manually pass it via ``graph.ainvoke(input, config={"callbacks": [...]})``.
    With ``create_react_agent`` and other prebuilt LangGraph constructs,
    users never see the invoke call directly, so the callback never fired.

    Returns True if the patch was applied (or already in place); False if
    Runnable could not be imported.
    """
    global _RUNNABLE_PATCHED
    if _RUNNABLE_PATCHED:
        return True
    try:
        from langchain_core.runnables.base import Runnable
    except ImportError:
        return False

    def _inject_callback(config: Any) -> Any:
        """Ensure our handler is in config['callbacks']."""
        if config is None:
            config = {}
        elif not isinstance(config, dict):
            # RunnableConfig is a TypedDict-as-dict; if someone passed
            # something else, leave it alone
            return config
        cbs = config.get("callbacks")
        if cbs is None:
            config["callbacks"] = [handler]
        elif isinstance(cbs, list):
            if not any(c is handler for c in cbs):
                cbs.append(handler)
        # If callbacks is a CallbackManager instance we leave it alone — the
        # CallbackManager already has its own handler list and re-adding
        # would be a no-op or worse a duplication.
        return config

    _orig_ainvoke = Runnable.ainvoke
    _orig_invoke = Runnable.invoke
    _orig_astream = Runnable.astream
    _orig_stream = Runnable.stream
    _orig_abatch = Runnable.abatch
    _orig_batch = Runnable.batch

    async def _ainvoke(self, input, config=None, **kwargs):
        return await _orig_ainvoke(self, input, _inject_callback(config), **kwargs)

    def _invoke(self, input, config=None, **kwargs):
        return _orig_invoke(self, input, _inject_callback(config), **kwargs)

    def _astream(self, input, config=None, **kwargs):
        return _orig_astream(self, input, _inject_callback(config), **kwargs)

    def _stream(self, input, config=None, **kwargs):
        return _orig_stream(self, input, _inject_callback(config), **kwargs)

    async def _abatch(self, inputs, config=None, **kwargs):
        # config may be a single dict or a list of dicts (per-input)
        if isinstance(config, list):
            config = [_inject_callback(c) for c in config]
        else:
            config = _inject_callback(config)
        return await _orig_abatch(self, inputs, config, **kwargs)

    def _batch(self, inputs, config=None, **kwargs):
        if isinstance(config, list):
            config = [_inject_callback(c) for c in config]
        else:
            config = _inject_callback(config)
        return _orig_batch(self, inputs, config, **kwargs)

    Runnable.ainvoke = _ainvoke  # type: ignore[assignment]
    Runnable.invoke = _invoke    # type: ignore[assignment]
    Runnable.astream = _astream  # type: ignore[assignment]
    Runnable.stream = _stream    # type: ignore[assignment]
    Runnable.abatch = _abatch    # type: ignore[assignment]
    Runnable.batch = _batch      # type: ignore[assignment]
    _RUNNABLE_PATCHED = True
    return True


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

    # v0.2.6 fix: dual auto-attach strategy:
    #
    # (a) Register via LangChain's `register_configure_hook` — this propagates
    #     the handler INHERITABLY through nested Runnables in create_react_agent
    #     / StateGraph / ToolNode dispatch paths, which simple top-level
    #     config injection doesn't reach.
    #
    # (b) Monkey-patch Runnable.invoke/ainvoke as a belt-and-suspenders
    #     fallback for LangChain versions where register_configure_hook
    #     doesn't exist or behaves differently.
    via_hook = _register_via_configure_hook(handler)
    auto_attached = _auto_attach_handler_to_runnable(handler)

    if via_hook or auto_attached:
        logger.info(
            "synapse.install(framework='langgraph'): SynapseLangGraphCallback "
            "registered via configure_hook=%s + Runnable monkey-patch=%s. "
            "Every LangChain/LangGraph tool call now flows through this handler "
            "(including nested ToolNode dispatches in create_react_agent). "
            "v0.2.6+ behavior.",
            via_hook, auto_attached,
        )
    else:
        logger.warning(
            "synapse.install(framework='langgraph'): callback registered but "
            "could not auto-attach to Runnable (langchain-core import failed). "
            "Pass config={'callbacks':[synapse.frameworks.langgraph.get_callback()]} "
            "manually to every graph.invoke()."
        )


# Self-register on import
register_framework("langgraph", _install_langgraph)
register_framework("langchain", _install_langgraph)
