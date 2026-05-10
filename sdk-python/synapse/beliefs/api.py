"""Public-facing belief API.

``synapse.emit_belief()`` — one-call belief emission, persists to state
graph + bus + runs live divergence detection. Returns the divergence
(if any) so the caller can react.

``synapse.list_divergences(session_id)`` — return all current
belief divergences for the session.

These are thin wrappers over the v0.1 Agent.emit_belief() and the new
live_detector module. They take care of agent caching, state graph
connection, and the divergence-after-emission step.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from .live_detector import LiveDivergenceResult, detect_live_divergence

logger = logging.getLogger(__name__)


async def emit_belief(
    *,
    agent: str,
    key: str,
    value: Any,
    session: Optional[str] = None,
    confidence: float = 0.9,
    source: str = "observed",
    evidence: Optional[str] = None,
    detect_divergence: bool = True,
) -> Optional[LiveDivergenceResult]:
    """Emit a BELIEF + run live divergence detection.

    Args:
        agent: agent id
        key: stable identifier ("revenue_formula", "primary_key", ...)
        value: the believed fact (any JSON-serializable value)
        session: session id (defaults to env SYNAPSE_SESSION_ID)
        confidence: 0.0 to 1.0 (default 0.9)
        source: "observed" | "inferred" | "assumed"
        evidence: optional supporting text
        detect_divergence: run live divergence after emission (default True)

    Returns:
        LiveDivergenceResult if a divergence was detected on this key,
        None otherwise.
    """
    from synapse.intend import _get_agent

    session_id = (
        session
        or os.environ.get("SYNAPSE_SESSION_ID")
        or "default_session"
    )

    syn_agent = None
    try:
        syn_agent = await _get_agent(agent, session_id)
    except Exception as e:
        logger.warning("synapse.emit_belief: failed to acquire agent (%s)", e)

    if syn_agent is None:
        # Offline mode — record locally, no divergence detection possible
        logger.debug("synapse.emit_belief: offline mode, no emission")
        return None

    try:
        await syn_agent.emit_belief(
            key=key, value=value,
            confidence=confidence, source=source,
            evidence=evidence,
        )
    except Exception as e:
        logger.warning("synapse.emit_belief: emit failed (%s)", e)
        return None

    # Persist to state graph (Agent.emit_belief publishes to bus but doesn't
    # write to PG — the coordinator usually picks up beliefs from the bus
    # and persists. For sub-second detection we need to write directly.
    await _persist_belief_to_state(
        agent=agent, session_id=session_id, key=key, value=value,
        confidence=confidence, source=source, evidence=evidence,
    )

    if not detect_divergence:
        return None

    return await detect_live_divergence(
        session_id=session_id, just_emitted_key=key,
    )


async def _persist_belief_to_state(
    *, agent: str, session_id: str, key: str, value: Any,
    confidence: float, source: str, evidence: Optional[str],
) -> None:
    """Direct upsert into the beliefs table, since the coordinator's
    30s tick is too slow for live divergence detection."""
    import json
    from synapse.intend import _get_or_init_runtime

    rt = _get_or_init_runtime()
    state = rt.get("state")
    if state is None:
        return

    try:
        # Backend-agnostic: both StateGraph (Postgres) and SqliteStateGraph
        # implement belief_upsert with the same signature.
        await state.belief_upsert(
            agent_id=agent, session_id=session_id, tenant_id=None,
            key=key, value=value,
            confidence=confidence, source=source, evidence=evidence,
        )
    except Exception as e:
        logger.warning("synapse.emit_belief: state upsert failed (%s)", e)


async def list_divergences(session_id: Optional[str] = None) -> list[LiveDivergenceResult]:
    """Return all current belief divergences for the session.

    Useful for inspecting end-of-run state, dashboards, audits.
    """
    from synapse.intend import _get_or_init_runtime
    from synapse.beliefs.divergence import (
        AgentBelief, beliefs_from_db_rows, detect_divergences,
    )

    rt = _get_or_init_runtime()
    state = rt.get("state")
    if state is None:
        return []

    sid = session_id or os.environ.get("SYNAPSE_SESSION_ID")
    if not sid:
        return []

    # Backend-agnostic — works against Postgres or SQLite state graphs.
    rows = await state.beliefs_for_session(sid)
    beliefs = beliefs_from_db_rows(rows)
    divs = detect_divergences(beliefs)
    out: list[LiveDivergenceResult] = []
    for d in divs:
        agents = sorted({b.agent_id for b in d.agents})
        distinct = list(d.distinct_values)
        out.append(
            LiveDivergenceResult(
                key=d.key,
                distinct_values=distinct,
                agents_involved=agents,
                severity=d.severity,
                rationale=(
                    f"BELIEF divergence on {d.key!r}: {len(agents)} agent(s) "
                    f"({', '.join(agents)}) hold {len(distinct)} distinct value(s): "
                    f"{distinct!r}. Severity={d.severity:.2f}."
                ),
            )
        )
    return out


async def divergences_for_key(session_id: str, key: str) -> Optional[LiveDivergenceResult]:
    """Convenience: divergence detection for a single belief key."""
    return await detect_live_divergence(session_id=session_id, just_emitted_key=key)
