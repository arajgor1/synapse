"""``synapse.install()`` — one-line bootstrap for any agent stack.

Configures the Synapse runtime in a single call:
  - Connects to bus + state graph (if URLs provided, else offline mode)
  - Stores LLM config (BYO via ``set_llm`` is the alternative)
  - Optionally hooks into a popular agent framework so its tool calls
    get auto-instrumented through ``synapse.intend()``

Examples:

    # Laziest — auto-detect everything
    synapse.install()

    # Explicit framework + LLM
    from anthropic import AsyncAnthropic
    synapse.install(
        framework="langgraph",
        llm=synapse.from_anthropic(AsyncAnthropic()),
    )

    # Self-hosted with custom backends
    synapse.install(
        bus_url="redis://localhost:6379/0",
        state_dsn="postgresql://synapse:synapse@localhost:5432/synapse",
        session_id="my_session",
        agent_id="my_agent",
    )
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from synapse.adapters.base import InferenceAdapter
from synapse.intend import _get_or_init_runtime, _ensure_connected, shutdown as intend_shutdown

logger = logging.getLogger(__name__)


_FRAMEWORK_REGISTRY: dict[str, Any] = {}


def register_framework(name: str, install_fn) -> None:
    """Plug-in entry point: register a framework adapter.

    ``install_fn`` is called when ``synapse.install(framework=name)`` runs.
    It should hook into the framework so tool dispatches get wrapped with
    ``synapse.intend()``. It receives ``opts`` (the install kwargs).
    """
    _FRAMEWORK_REGISTRY[name] = install_fn


def _autodetect_framework() -> Optional[str]:
    """Best-effort detection of which framework is in use.

    Looks at sys.modules first (cheapest), then falls back to import-checks.
    """
    import sys
    candidates = (
        "langgraph", "crewai",
        "autogen", "autogen_agentchat", "autogen_core",
        "agents", "openai_agents", "openai_swarm",
        "smolagents", "pydantic_ai",
    )
    for c in candidates:
        if c in sys.modules:
            return _normalize(c)
    # Don't import anything we don't have to — just return None
    return None


def _normalize(mod: str) -> str:
    if mod.startswith("autogen"):
        return "autogen"
    if mod in ("openai_swarm", "agents"):
        return "openai_agents"
    return mod


def install(
    *,
    framework: Optional[str] = None,
    llm: Optional[InferenceAdapter] = None,
    bus_url: Optional[str] = None,
    state_dsn: Optional[str] = None,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    auto: bool = True,
    merge_policy: Any = None,                    # v0.2-w4
    critical_scopes: Optional[list[str]] = None,
    emit_beliefs_from_tool_results: bool = False,  # v0.2-w5
    auto_router: bool = False,                     # v0.2.6
    **framework_opts: Any,
) -> dict[str, Any]:
    """Configure Synapse and (optionally) hook into a known framework.

    Args:
        framework: Explicit framework name (e.g. "langgraph"). If None and
            ``auto=True``, Synapse attempts to detect from sys.modules.
        llm: BYO-LLM adapter. If None, leaves whatever was set with
            ``synapse.set_llm()`` in place.
        bus_url: Redis URL. Falls back to SYNAPSE_REDIS_URL env var. If
            still unset, runs in offline mode (no envelopes emitted).
        state_dsn: Postgres DSN. Falls back to SYNAPSE_POSTGRES_DSN.
        session_id: Default session id; written to env if not already set.
        agent_id: Default agent id; written to env if not already set.
        auto: Auto-detect framework if not explicit. Default True.
        framework_opts: Forwarded to the framework adapter's install fn.

    Returns:
        A dict with ``{framework, mode, llm, hooks_installed}``.
    """
    if llm is not None:
        from synapse.llm.config import set_llm as _set_llm
        _set_llm(llm)

    if session_id and not os.environ.get("SYNAPSE_SESSION_ID"):
        os.environ["SYNAPSE_SESSION_ID"] = session_id
    if agent_id and not os.environ.get("SYNAPSE_DEFAULT_AGENT_ID"):
        os.environ["SYNAPSE_DEFAULT_AGENT_ID"] = agent_id

    rt = _get_or_init_runtime(bus_url=bus_url, state_dsn=state_dsn)

    # Stash policy defaults so synapse.intend() picks them up
    from synapse.policies import resolve_policy, normalize_critical_scopes
    policy_defaults = rt.setdefault("policy_defaults", {})
    if merge_policy is not None:
        policy_defaults["merge_policy"] = resolve_policy(merge_policy)
    if critical_scopes is not None:
        policy_defaults["critical_scopes"] = normalize_critical_scopes(critical_scopes)
    if emit_beliefs_from_tool_results:
        policy_defaults["emit_beliefs_from_tool_results"] = True

    if framework is None and auto:
        framework = _autodetect_framework()

    # v0.2.6: optionally auto-spawn an L2 Router worker. Without a Router,
    # INTENTIONs are persisted to the state graph but CONFLICT envelopes
    # never get routed to agent inboxes — Phase 7b finding. The Router
    # normally runs as a separate `synapse up` process; for library users
    # who don't want to manage that, this spawns it as a sibling asyncio
    # task on the current loop.
    if auto_router:
        _try_spawn_router(rt, session_id=session_id)

    hooks: list[str] = []
    if framework:
        # Lazy-import the adapter and register if not already
        _ensure_framework_loaded(framework)
        install_fn = _FRAMEWORK_REGISTRY.get(framework)
        if install_fn is None:
            logger.warning(
                "synapse.install: no adapter registered for framework=%r. "
                "Available: %s. Falling back to manual synapse.intend().",
                framework, sorted(_FRAMEWORK_REGISTRY),
            )
        else:
            install_fn(framework_opts)
            hooks.append(framework)

    return {
        "framework": framework,
        "mode": rt.get("mode"),
        "bus_url": rt.get("bus_url"),
        "state_dsn": rt.get("state_dsn"),
        "hooks_installed": hooks,
        "merge_policy": getattr(policy_defaults.get("merge_policy"), "name", None),
        "critical_scopes": policy_defaults.get("critical_scopes") or [],
        "emit_beliefs_from_tool_results": bool(policy_defaults.get("emit_beliefs_from_tool_results")),
    }


def _try_spawn_router(rt: dict[str, Any], *, session_id: Optional[str]) -> None:
    """v0.2.6: spawn an L2 Router task on the current asyncio loop so
    CONFLICT envelopes route to agent inboxes without requiring an
    external ``synapse up`` process.

    No-op if:
      - no asyncio loop is currently running (we're in a sync context;
        the Router needs a loop to drive its consumer group)
      - bus or state isn't connected (offline mode)
      - a Router is already running for this session
    """
    bus = rt.get("bus")
    state = rt.get("state")
    if bus is None or state is None:
        logger.info("synapse.install(auto_router=True): no bus/state — "
                    "Router not started (offline mode)")
        return

    sid = session_id or os.environ.get("SYNAPSE_SESSION_ID") or "default_session"

    routers = rt.setdefault("routers", {})
    if sid in routers and routers[sid].get("task") is not None:
        # Already running for this session
        return

    try:
        import asyncio as _asyncio
        loop = _asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("synapse.install(auto_router=True): no running asyncio "
                       "loop — cannot spawn Router. Call install() from "
                       "inside an async function, or run `synapse up` as a "
                       "separate process.")
        return

    try:
        from runtime.router.worker import Router
    except ImportError as e:
        logger.warning("synapse.install(auto_router=True): cannot import "
                       "runtime.router.worker.Router (%s). Skipping spawn.", e)
        return

    try:
        router = Router(bus, state, sid, consumer=f"auto_router_{sid}")
        task = loop.create_task(router.run(), name=f"synapse-router-{sid}")
        routers[sid] = {"router": router, "task": task}
        logger.info("synapse.install(auto_router=True): spawned Router for "
                    "session=%s on current loop", sid)
    except Exception as e:
        logger.warning("synapse.install(auto_router=True): Router spawn "
                       "failed (%s)", e)


def _ensure_framework_loaded(name: str) -> None:
    """Lazy-import the framework adapter so it self-registers."""
    try:
        if name == "langgraph":
            from synapse.frameworks import langgraph  # noqa: F401
        elif name == "crewai":
            from synapse.frameworks import crewai  # noqa: F401
        elif name in ("autogen", "autogen_agentchat", "autogen_core"):
            from synapse.frameworks import autogen  # noqa: F401
        elif name in ("openai_agents", "openai_agents_sdk", "swarm"):
            from synapse.frameworks import openai_agents  # noqa: F401
        elif name in ("pydantic_ai", "pydantic-ai"):
            from synapse.frameworks import pydantic_ai  # noqa: F401
        elif name == "smolagents":
            from synapse.frameworks import smolagents  # noqa: F401
        elif name == "hermes":
            from synapse.frameworks import hermes  # noqa: F401
        elif name in ("strands", "strands_agents", "strands-agents"):
            from synapse.frameworks import strands  # noqa: F401
        elif name == "agno":
            from synapse.frameworks import agno  # noqa: F401
        elif name in ("llama_index", "llamaindex", "llama-index"):
            from synapse.frameworks import llama_index  # noqa: F401
        elif name in ("google_adk", "google-adk", "adk"):
            from synapse.frameworks import google_adk  # noqa: F401
        elif name in ("otel", "opentelemetry", "otel_live"):
            from synapse.frameworks import otel_live  # noqa: F401
        elif name == "langchain":
            from synapse.frameworks import langchain  # noqa: F401
    except ImportError as e:
        logger.warning(
            "synapse.install: framework adapter %r not yet shipped or its "
            "underlying package isn't installed (%s). Use synapse.intend() "
            "manually for now.", name, e,
        )


async def shutdown() -> None:
    """Tear down: close connections, drop caches. Safe to call repeatedly."""
    await intend_shutdown()
