"""Belief divergence detection.

When multiple agents assert different values for the same belief key, the
divergence detector flags it. The coordinator can then synthesize a
clarification signal back to the agents.

Pure-function module — no I/O, fully testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class AgentBelief:
    agent_id: str
    key: str
    value: Any
    confidence: float
    source: str   # "observed" | "inferred" | "assumed"

    @property
    def evidential_weight(self) -> float:
        """Combined confidence + source-rank score, 0..1.

        observed > inferred > assumed (confidence multiplier).
        """
        rank = {"observed": 1.0, "inferred": 0.7, "assumed": 0.4}.get(self.source, 0.5)
        return min(1.0, max(0.0, self.confidence * rank))


@dataclass(frozen=True)
class BeliefDivergence:
    """Two or more agents holding distinct values for the same key."""

    key: str
    agents: tuple[AgentBelief, ...]   # at least 2 distinct values
    severity: float                    # 0..1, higher = more confident disagreement

    @property
    def distinct_values(self) -> tuple[Any, ...]:
        seen: list[Any] = []
        for b in self.agents:
            if b.value not in seen:
                seen.append(b.value)
        return tuple(seen)


def _values_equal(a: Any, b: Any) -> bool:
    """Structural equality, with float fuzz."""
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) < 1e-9
    return a == b


def detect_divergences(beliefs: Iterable[AgentBelief]) -> list[BeliefDivergence]:
    """Group beliefs by key. Within each key, find sets of agents with
    distinct values. Returns one BeliefDivergence per key with conflict.

    severity = average evidential_weight across the disagreeing agents,
    scaled by how many agents disagree (more agents -> higher severity).
    """
    by_key: dict[str, list[AgentBelief]] = {}
    for b in beliefs:
        by_key.setdefault(b.key, []).append(b)

    out: list[BeliefDivergence] = []
    for key, group in by_key.items():
        if len(group) < 2:
            continue
        # Find distinct values
        distinct: list[Any] = []
        for b in group:
            if not any(_values_equal(b.value, d) for d in distinct):
                distinct.append(b.value)
        if len(distinct) < 2:
            continue
        # Compute severity
        avg_weight = sum(b.evidential_weight for b in group) / len(group)
        scale = min(1.0, len(distinct) / 3.0)  # 2 distinct -> 0.67, 3+ -> 1.0
        severity = min(1.0, avg_weight * (0.5 + 0.5 * scale))
        out.append(BeliefDivergence(key=key, agents=tuple(group), severity=severity))

    # Highest severity first
    out.sort(key=lambda d: d.severity, reverse=True)
    return out


def beliefs_from_db_rows(rows: Iterable[dict[str, Any]]) -> list[AgentBelief]:
    """Convert StateGraph belief rows into AgentBelief objects."""
    out: list[AgentBelief] = []
    for r in rows:
        out.append(AgentBelief(
            agent_id=r["agent_id"],
            key=r["key"],
            value=r["value"],
            confidence=float(r["confidence"]),
            source=r["source"],
        ))
    return out
