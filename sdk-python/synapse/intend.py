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

import asyncio
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

    # v0.2 week 4: filled in by AutoMergePolicy when it succeeds. The
    # caller should use ``merged_action`` instead of their original
    # tool args / content.
    merged_action: Optional[dict[str, Any]] = None
    # The MergePolicy's rationale string (logged + surfaced in resolution)
    policy_rationale: Optional[str] = None
    # Set when a policy decides ABORT (the caller's framework handles it)
    aborted: bool = False

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
    merge_policy: Any = None,                # v0.2-w4: MergePolicy | str | None
    critical_scopes: Optional[list[str]] = None,
    proposed_action: Optional[dict[str, Any]] = None,
):
    """Wrap a tool dispatch with Synapse coordination.

    On enter:
      - Emit INTENTION with the given scope
      - Optionally drain inbox for CONFLICT signals (gate window)
      - If conflicts found, run the configured ``merge_policy``:
          * critical_scopes match  → force ABORT (raises SynapseConflict)
          * MergePolicy.abort      → raise SynapseConflict
          * MergePolicy.wait       → block briefly + retry
          * MergePolicy.auto_merge → call user's LLM, fill handle.merged_action
          * MergePolicy.redirect   → log rationale, set handle.policy_rationale
      - Yield IntentionHandle so the caller can inspect + record state_diff

    On exit:
      - Emit RESOLUTION with the outcome (success / failure)

    Args:
        merge_policy: a ``synapse.MergePolicy.*`` constant, a custom
            MergePolicy instance, a string name ("redirect"/"wait"/...),
            or None to fall back to ``install()``-time default + a final
            fallback of redirect.
        critical_scopes: glob patterns. If any matches a scope on a
            CONFLICT-bearing intention, force ABORT regardless of policy.
        proposed_action: required for ``auto_merge`` — the tool args /
            content the agent is about to use. Optional otherwise.

    Offline mode (no bus): body still runs, no envelopes emitted, no
    policy applied (no conflicts can fire).
    """
    from synapse.policies import resolve_policy
    from synapse.policies.base import MergeDecision, SynapseConflict
    from synapse.policies.critical import (
        critical_scope_match, normalize_critical_scopes,
    )

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

    # Resolve effective policy + critical_scopes from caller > install-time > defaults
    install_defaults = _runtime.get("policy_defaults") or {}
    policy = resolve_policy(merge_policy)
    if policy is None:
        policy = resolve_policy(install_defaults.get("merge_policy"))
    crit_scopes = normalize_critical_scopes(
        critical_scopes if critical_scopes is not None
        else install_defaults.get("critical_scopes")
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

    # Apply MergePolicy if conflicts surfaced
    if handle.has_conflicts:
        # 1. critical_scopes hard-block first
        match = critical_scope_match(handle.scope, crit_scopes)
        if match:
            rationale = (
                f"Critical scope match: {match!r} forced ABORT on {handle.scope}. "
                f"{len(handle.conflicts)} conflicting intention(s)."
            )
            handle.aborted = True
            handle.policy_rationale = rationale
            handle.mark_failed(rationale)
            if syn_agent is not None and handle.intention_id:
                try:
                    await syn_agent.emit_resolution(
                        intention_id=handle.intention_id,
                        outcome="failure",
                        state_diff={"error": rationale, "policy": "critical_scope"},
                    )
                except Exception:
                    pass
            raise SynapseConflict(handle.conflicts, handle.scope, rationale)

        # 2. configured policy
        if policy is not None:
            try:
                action = await policy.resolve(handle, handle.conflicts, proposed_action)
            except Exception as e:
                logger.warning("synapse.intend: merge_policy.resolve raised (%s); proceeding", e)
                action = None
            if action is not None:
                handle.policy_rationale = action.rationale
                if action.decision == MergeDecision.ABORT:
                    handle.aborted = True
                    handle.mark_failed(action.rationale)
                    if syn_agent is not None and handle.intention_id:
                        try:
                            await syn_agent.emit_resolution(
                                intention_id=handle.intention_id,
                                outcome="failure",
                                state_diff={"error": action.rationale, "policy": policy.name},
                            )
                        except Exception:
                            pass
                    raise SynapseConflict(handle.conflicts, handle.scope, action.rationale)
                elif action.decision == MergeDecision.MERGED:
                    handle.merged_action = action.merged_action
                elif action.decision == MergeDecision.WAIT:
                    # Best-effort: sleep the timeout, then proceed.
                    # A full implementation would re-poll the state graph.
                    await asyncio.sleep(action.wait_timeout_ms / 1000)
                # MergeDecision.PROCEED needs no action

    started = time.time()
    try:
        yield handle
    except Exception as e:
        handle.mark_failed(str(e))
        raise
    finally:
        if syn_agent is not None and handle.intention_id and not handle.aborted:
            try:
                sd = handle.state_diff or (
                    {"error": handle.error_message} if handle.error_message else {}
                )
                if handle.policy_rationale:
                    sd = {**sd, "policy_rationale": handle.policy_rationale}
                await syn_agent.emit_resolution(
                    intention_id=handle.intention_id,
                    outcome=handle.outcome,
                    state_diff=sd,
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
