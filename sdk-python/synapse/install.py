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
        "langgraph", "crewai", "autogen", "autogen_agentchat",
        "openai_swarm", "smolagents", "pydantic_ai",
    )
    for c in candidates:
        if c in sys.modules:
            return _normalize(c)
    # Don't import anything we don't have to — just return None
    return None


def _normalize(mod: str) -> str:
    if mod.startswith("autogen"):
        return "autogen"
    if mod == "openai_swarm":
        return "swarm"
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

    if framework is None and auto:
        framework = _autodetect_framework()

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
    }


def _ensure_framework_loaded(name: str) -> None:
    """Lazy-import the framework adapter so it self-registers."""
    try:
        if name == "langgraph":
            from synapse.frameworks import langgraph  # noqa: F401
        elif name == "crewai":
            from synapse.frameworks import crewai  # noqa: F401
        elif name in ("autogen", "autogen_agentchat"):
            from synapse.frameworks import autogen  # noqa: F401
    except ImportError as e:
        logger.warning(
            "synapse.install: framework adapter %r not yet shipped or its "
            "underlying package isn't installed (%s). Use synapse.intend() "
            "manually for now.", name, e,
        )


async def shutdown() -> None:
    """Tear down: close connections, drop caches. Safe to call repeatedly."""
    await intend_shutdown()
