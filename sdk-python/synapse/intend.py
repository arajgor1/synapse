"""``synapse.intend()`` — the universal context-manager SDK.

Wraps a tool dispatch with INTENTION emission, conflict detection, and
RESOLUTION on exit. Works in any Python codebase regardless of which
agent framework is in use; framework-specific adapters (LangGraph,
CrewAI, AutoGen, etc.) all use this internally.

Example:

    import synapse

    async with synapse.intend(
        scope=["repo.fs.auth.py:w"],
        agent="code-reviewer",
        expected_outcome="fix CVE-2026-1234",
    ) as i:
        if i.has_conflicts:
            # caller decides: redirect (re-prompt LLM with other agent's
            # work), wait, abort, or proceed anyway
            await i.pivot()
        result = await my_tool_call()
        i.set_state_diff({"lines_changed": 47})
    # RESOLUTION emitted automatically on exit (success or failure)
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Optional

from synapse.agent import Agent
from synapse.messages import Conflict

logger = logging.getLogger(__name__)


@dataclass
class IntentionHandle:
    """Returned from ``synapse.intend(...)``. Lets the caller inspect
    detected conflicts and choose how to react.
    """
    intention_id: str
    scope: list[str]
    agent_id: str
    session_id: str
    conflicts: list[Conflict] = field(default_factory=list)

    # Mutable: the caller fills these during the with-block
    state_diff: dict[str, Any] = field(default_factory=dict)
    side_effects: list[str] = field(default_factory=list)
    outcome: str = "success"
    error_message: Optional[str] = None

    @property
    def has_conflicts(self) -> bool:
        return len(self.conflicts) > 0

    def set_state_diff(self, diff: dict[str, Any]) -> None:
        self.state_diff.update(diff)

    def add_side_effect(self, effect: str) -> None:
        self.side_effects.append(effect)

    def mark_failed(self, message: str = "") -> None:
        """Mark this intention as failed (RESOLUTION will record outcome=failure)."""
        self.outcome = "failure"
        self.error_message = message[:200] if message else None


# ---------------------------------------------------------------------------
# Module-level runtime: lazy bus + state graph + per-(session,agent) Agent cache
# ---------------------------------------------------------------------------
_runtime: dict[str, Any] = {}


def _get_or_init_runtime(
    *,
    bus_url: Optional[str] = None,
    state_dsn: Optional[str] = None,
) -> dict[str, Any]:
    """Idempotent runtime setup. ``synapse.install()`` configures this
    explicitly; ``intend()`` falls back to env vars if not."""
    if _runtime.get("bus") is not None:
        return _runtime

    bus_url = bus_url or os.environ.get("SYNAPSE_REDIS_URL")
    state_dsn = state_dsn or os.environ.get("SYNAPSE_POSTGRES_DSN")

    if not bus_url:
        # Fully offline mode — intend() becomes a no-op recorder.
        _runtime["mode"] = "offline"
        return _runtime

    from synapse.bus import Bus

    _runtime["bus"] = Bus(bus_url)
    _runtime["bus_url"] = bus_url
    _runtime["state_dsn"] = state_dsn
    _runtime["agents"] = {}
    _runtime["mode"] = "live"
    _runtime["connected"] = False
    return _runtime


async def _ensure_connected() -> dict[str, Any]:
    rt = _get_or_init_runtime()
    if rt.get("mode") == "offline":
        return rt
    if rt.get("connected"):
        return rt

    bus = rt["bus"]
    await bus.connect()

    state_dsn = rt.get("state_dsn")
    if state_dsn:
        from synapse.state import StateGraph
        state = StateGraph(state_dsn)
        await state.connect()
        rt["state"] = state

    rt["connected"] = True
    return rt


async def _get_agent(agent_id: str, session_id: str) -> Optional[Agent]:
    """Return (and cache) a Synapse Agent for the given (agent_id, session_id).

    In offline mode (no bus configured), returns None — the caller treats
    intend() as a recording no-op.
    """
    rt = await _ensure_connected()
    if rt.get("mode") == "offline":
        return None

    cache_key = f"{session_id}::{agent_id}"
    agents = rt.setdefault("agents", {})
    if cache_key in agents:
        return agents[cache_key]

    from synapse.adapters.mock import MockAdapter

    agent = Agent(
        id=agent_id,
        session=session_id,
        backend=MockAdapter(),
        bus=rt["bus"],
        state=rt.get("state"),
        subscribes=[],
    )
    await agent._connect()
    if rt.get("state") is not None:
        await agent._register()
    agents[cache_key] = agent
    return agent


# ---------------------------------------------------------------------------
# The main entry point — async context manager
# ---------------------------------------------------------------------------
@asynccontextmanager
async def intend(
    *,
    scope: list[str],
    agent: str,
    session: Optional[str] = None,
    expected_outcome: str = "",
    blocking: bool = True,
    gate_ms: int = 50,
    estimated_duration_ms: Optional[int] = None,
    uncertainty: Optional[str] = None,
):
    """Wrap a tool dispatch with Synapse coordination.

    On enter:
      - Emit INTENTION with the given scope
      - Optionally drain inbox for CONFLICT signals (gate window)
      - Yield an IntentionHandle so the caller can inspect conflicts +
        record state_diff / side_effects

    On exit:
      - Emit RESOLUTION with the outcome (success / failure)

    If no bus is configured (offline mode), the body still runs — Synapse
    just doesn't emit envelopes. Useful for tests + CI where Redis isn't up.
    """
    session_id = (
        session
        or os.environ.get("SYNAPSE_SESSION_ID")
        or "default_session"
    )

    handle = IntentionHandle(
        intention_id="",
        scope=list(scope),
        agent_id=agent,
        session_id=session_id,
    )

    syn_agent = None
    try:
        syn_agent = await _get_agent(agent, session_id)
    except Exception as e:
        logger.warning("synapse.intend: failed to set up agent (%s); offline mode", e)

    if syn_agent is not None:
        try:
            intention_id, conflicts = await syn_agent.emit_intention(
                action={"description": expected_outcome or f"intend:{agent}"},
                scope=list(scope),
                expected_outcome=expected_outcome or "tool dispatch",
                blocking=blocking,
                gate_ms=gate_ms,
                **({"estimated_duration_ms": estimated_duration_ms}
                   if estimated_duration_ms is not None else {}),
                **({"uncertainty": uncertainty} if uncertainty is not None else {}),
            )
            handle.intention_id = intention_id
            handle.conflicts = conflicts or []
        except Exception as e:
            logger.warning("synapse.intend: emit_intention failed (%s); proceeding anyway", e)

    started = time.time()
    try:
        yield handle
    except Exception as e:
        handle.mark_failed(str(e))
        raise
    finally:
        if syn_agent is not None and handle.intention_id:
            try:
                await syn_agent.emit_resolution(
                    intention_id=handle.intention_id,
                    outcome=handle.outcome,
                    state_diff=handle.state_diff or (
                        {"error": handle.error_message} if handle.error_message else {}
                    ),
                    side_effects=handle.side_effects or None,
                )
            except Exception as e:
                logger.warning("synapse.intend: emit_resolution failed (%s)", e)


# ---------------------------------------------------------------------------
# Cleanup helpers — used by tests and by ``synapse.install`` shutdown
# ---------------------------------------------------------------------------
async def shutdown() -> None:
    """Close bus + state graph connections, drop the agent cache.

    Safe to call multiple times; safe to call when nothing was set up.
    """
    rt = _runtime
    if rt.get("connected"):
        bus = rt.get("bus")
        if bus is not None:
            try:
                await bus.close()
            except Exception:
                pass
        state = rt.get("state")
        if state is not None:
            try:
                await state.close()
            except Exception:
                pass
    _runtime.clear()
