"""Per-agent-pair Semantic Alignment Score (SAS).

Inspired by the Drift Monitor in Acharya 2026 SCF (arXiv 2604.16339).
Quantifies how much two agents in the same session disagree across
their observed actions. A low SAS is a signal that even without a
hard CONFLICT firing, the two agents have diverging operational models
of the system — worth surfacing as a soft warning before the next
CONFLICT lands.

SAS formula:
    SAS = 0.5 * entity_overlap     # do they touch the same scopes?
        + 0.3 * action_consistency # are their tool-name patterns aligned?
        + 0.2 * temporal_alignment # do they interleave or one-after-other?

All three components are in [0,1]; SAS is in [0,1]. SAS=1.0 means
identical operational footprint; SAS=0.0 means completely disjoint.

The "right" SAS depends on the workflow. Two agents working on disjoint
files SHOULD have low SAS — that's not drift, that's division of labor.
The audit consumer should set a per-session expectation.

This module is a pure analyzer over already-collected AuditEvents — no
LLM calls, no live Synapse runtime needed.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, asdict
from typing import Any

from .events import AuditEvent


@dataclass
class AgentPairSAS:
    """SAS for one ordered pair of agents in one session."""
    session_id: str
    agent_a: str
    agent_b: str
    sas: float                    # composite score in [0, 1]
    entity_overlap: float         # in [0, 1]
    action_consistency: float     # in [0, 1]
    temporal_alignment: float     # in [0, 1]
    n_events_a: int
    n_events_b: int
    shared_scopes: list[str]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["sas"] = round(self.sas, 4)
        d["entity_overlap"] = round(self.entity_overlap, 4)
        d["action_consistency"] = round(self.action_consistency, 4)
        d["temporal_alignment"] = round(self.temporal_alignment, 4)
        return d


def _entity_overlap(scopes_a: set[str], scopes_b: set[str]) -> float:
    """Jaccard of scope sets, ignoring action-suffix (:w / :r)."""
    base_a = {s.split(":")[0] for s in scopes_a if s}
    base_b = {s.split(":")[0] for s in scopes_b if s}
    if not base_a and not base_b:
        return 0.0
    inter = base_a & base_b
    union = base_a | base_b
    return len(inter) / len(union) if union else 0.0


def _action_consistency(tools_a: list[str], tools_b: list[str]) -> float:
    """How similar are the tool-call distributions?

    1 - 0.5 * total-variation distance between the two normalized
    histograms over tool names.
    """
    if not tools_a or not tools_b:
        return 0.0
    total = len(tools_a) + len(tools_b)
    counts: dict[str, int] = defaultdict(int)
    for t in tools_a:
        counts[t] += 1
    for t in tools_b:
        counts[t] += 1
    a_size = len(tools_a)
    b_size = len(tools_b)
    tv = 0.0
    for tool, c in counts.items():
        # marginalize per-side
        ca = sum(1 for t in tools_a if t == tool) / a_size if a_size else 0.0
        cb = sum(1 for t in tools_b if t == tool) / b_size if b_size else 0.0
        tv += abs(ca - cb)
    return max(0.0, 1.0 - 0.5 * tv)


def _temporal_alignment(events_a: list[AuditEvent], events_b: list[AuditEvent]) -> float:
    """Do A and B interleave during the same window, or are they
    sequential / disjoint?

    1.0 = strong overlap (same time window); 0.0 = fully disjoint.
    Computed as overlap_seconds / union_seconds.
    """
    if not events_a or not events_b:
        return 0.0
    a_start = min(e.ts_start_ms for e in events_a)
    a_end = max(e.ts_end_ms for e in events_a)
    b_start = min(e.ts_start_ms for e in events_b)
    b_end = max(e.ts_end_ms for e in events_b)
    overlap = max(0, min(a_end, b_end) - max(a_start, b_start))
    union = max(a_end, b_end) - min(a_start, b_start)
    return overlap / union if union > 0 else 1.0


def compute_sas(events: list[AuditEvent]) -> list[AgentPairSAS]:
    """One AgentPairSAS per (session, agent_a < agent_b) pair."""
    by_session_agent: dict[tuple[str, str], list[AuditEvent]] = defaultdict(list)
    for ev in events:
        by_session_agent[(ev.session_id, ev.agent_id)].append(ev)

    # Group agents per session
    sessions: dict[str, list[str]] = defaultdict(list)
    for (sess, agent) in by_session_agent.keys():
        sessions[sess].append(agent)

    out: list[AgentPairSAS] = []
    for sess, agents in sessions.items():
        agents = sorted(set(agents))
        for i in range(len(agents)):
            for j in range(i + 1, len(agents)):
                a, b = agents[i], agents[j]
                ev_a = by_session_agent[(sess, a)]
                ev_b = by_session_agent[(sess, b)]

                scopes_a = {s for e in ev_a for s in (e.scope_inferred or [])}
                scopes_b = {s for e in ev_b for s in (e.scope_inferred or [])}
                tools_a = [e.tool_name for e in ev_a]
                tools_b = [e.tool_name for e in ev_b]

                eo = _entity_overlap(scopes_a, scopes_b)
                ac = _action_consistency(tools_a, tools_b)
                ta = _temporal_alignment(ev_a, ev_b)
                sas = 0.5 * eo + 0.3 * ac + 0.2 * ta

                shared_base = {s.split(":")[0] for s in scopes_a} & {
                    s.split(":")[0] for s in scopes_b
                }

                out.append(AgentPairSAS(
                    session_id=sess,
                    agent_a=a,
                    agent_b=b,
                    sas=sas,
                    entity_overlap=eo,
                    action_consistency=ac,
                    temporal_alignment=ta,
                    n_events_a=len(ev_a),
                    n_events_b=len(ev_b),
                    shared_scopes=sorted(shared_base),
                ))
    return out
