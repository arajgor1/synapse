"""Hermes adapter for ``synapse.install(framework="hermes")``.

The v0.1 ``synapse.integrations.hermes_integration`` module exposes
``install_hermes_synapse_hooks()`` and ``wrap_tool_call_for_synapse()``.
This v0.2 adapter is a thin compatibility layer that wires the existing
hooks into the new universal ``synapse.install()`` pattern.

Existing v0.1 callers using ``wrap_tool_call_for_synapse`` directly keep
working unchanged. New users get the same experience as other v0.2
integrations: ``synapse.install(framework="hermes")`` and you're done.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from synapse.install import register_framework
from synapse.intend import _ensure_connected

logger = logging.getLogger(__name__)


def _install_hermes(opts: dict[str, Any]) -> None:
    """Bootstrap the v0.1 Hermes integration via the v0.2 install path.

    Runs ``install_hermes_synapse_hooks()`` against the bus + state graph
    that ``synapse.install()`` already configured. Multi-agent flows use
    the existing ``register_synapse_agent()`` API.
    """
    try:
        from synapse.integrations.hermes_integration import (
            install_hermes_synapse_hooks,
        )
    except ImportError:
        logger.warning("synapse.install(framework='hermes'): hermes_integration not importable")
        return

    from synapse.agent_context import current_agent_id
    session_id = opts.get("session_id") or os.environ.get("SYNAPSE_SESSION_ID", "hermes_default_session")
    # Hermes is a single-agent integration; honour ContextVar / env vars
    # before falling back to the legacy "hermes_main" sentinel.
    agent_id = opts.get("agent_id") or current_agent_id(default="hermes_main")
    gate_ms = int(opts.get("gate_ms", os.environ.get("SYNAPSE_GATE_MS", "50")))

    async def _bootstrap() -> None:
        rt = await _ensure_connected()
        if rt.get("mode") == "offline":
            logger.warning(
                "synapse.install(framework='hermes'): no bus configured. "
                "Set SYNAPSE_REDIS_URL / SYNAPSE_POSTGRES_DSN or pass bus_url=/state_dsn= "
                "to synapse.install()."
            )
            return
        bus = rt["bus"]
        state = rt.get("state")
        if state is None:
            logger.warning(
                "synapse.install(framework='hermes'): no Postgres state graph. "
                "Hermes needs the state graph for multi-agent intention persistence."
            )
            return
        await install_hermes_synapse_hooks(
            bus=bus, state=state,
            session_id=session_id,
            agent_id=agent_id,
            gate_ms=gate_ms,
        )
        logger.info(
            "synapse.install(framework='hermes'): hooks installed for session=%s agent=%s",
            session_id, agent_id,
        )

    # If a loop is running, schedule onto it; otherwise create one fresh.
    # Use get_running_loop() — get_event_loop() is deprecated in 3.12+.
    try:
        loop = asyncio.get_running_loop()
        asyncio.ensure_future(_bootstrap(), loop=loop)
        return
    except RuntimeError:
        pass
    asyncio.run(_bootstrap())


register_framework("hermes", _install_hermes)
