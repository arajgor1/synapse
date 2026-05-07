"""Per-emission divergence detection.

The coordinator's 30-second tick is too slow for live coordination.
This module re-runs the existing divergence detector against the state
graph immediately after a BELIEF is emitted. If divergence is found, it
returns a structured result that intend() / framework adapters can act on.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class LiveDivergenceResult:
    """One divergence detected on the just-emitted BELIEF's key."""
    key: str
    distinct_values: list[Any]
    agents_involved: list[str]
    severity: float
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "distinct_values": list(self.distinct_values),
            "agents_involved": list(self.agents_involved),
            "severity": self.severity,
            "rationale": self.rationale,
        }


async def detect_live_divergence(
    *,
    session_id: str,
    just_emitted_key: str,
) -> Optional[LiveDivergenceResult]:
    """Pull all beliefs for ``session_id`` matching ``just_emitted_key``
    from the state graph, run divergence detection on them, return the
    result if ≥2 distinct values exist.

    Returns None if no state graph is configured, no divergence found,
    or only one agent has emitted on this key.
    """
    from synapse.intend import _get_or_init_runtime
    from synapse.beliefs.divergence import AgentBelief, detect_divergences

    rt = _get_or_init_runtime()
    state = rt.get("state")
    if state is None:
        return None

    rows = await state.pool.fetch(
        """
        SELECT agent_id, key, value, confidence, source
        FROM beliefs
        WHERE session_id = $1 AND key = $2
        """,
        session_id, just_emitted_key,
    )
    if len(rows) < 2:
        return None

    beliefs = [
        AgentBelief(
            agent_id=r["agent_id"],
            key=r["key"],
            value=r["value"],
            confidence=float(r["confidence"]),
            source=r["source"],
        )
        for r in rows
    ]

    divs = detect_divergences(beliefs)
    if not divs:
        return None

    # Single key was queried, so at most one divergence
    d = divs[0]
    distinct = list(d.distinct_values)
    agents = sorted({b.agent_id for b in d.agents})
    rationale = (
        f"BELIEF divergence on {d.key!r}: {len(agents)} agent(s) "
        f"({', '.join(agents)}) hold {len(distinct)} distinct value(s): "
        f"{distinct!r}. Severity={d.severity:.2f}."
    )
    return LiveDivergenceResult(
        key=d.key,
        distinct_values=distinct,
        agents_involved=agents,
        severity=d.severity,
        rationale=rationale,
    )
