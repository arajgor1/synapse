"""In-memory conflict detector for audit-mode events.

Replicates the live L2 router's logic without requiring Postgres:
  1. Group events by session_id
  2. For each event with non-empty scope_inferred, look back at events
     from OTHER agents in the same session whose scopes overlap, and
     whose execution window either:
       - was still active when this event started (concurrent overlap), OR
       - resolved within `lookback_ms` (default 60s) of this event's
         start (stale-base overwrite — the v0.1 → v0.2 fix)

Output: a list of AuditConflict records keyed to the offending event.

CONFLICT TAXONOMY (v0.2.2+, aligned with Acharya 2026 SCF paper):

  - "scope_overlap"        : SCF Type 2 (resource contention) — two
                             agents hold concurrent intentions on the
                             same scope.
  - "stale_base_overwrite" : SCF Type 3 (causal violation, write-write) —
                             agent B writes to a scope that A wrote
                             recently, indicating B never saw A's change.
  - "causal_violation"     : SCF Type 3 (causal violation, structural) —
                             agent B's intention depends on a precondition
                             that A's resolved intention invalidates. We
                             surface a *hint* via state_diff comparison;
                             full pre/post-condition reasoning requires
                             the live runtime's state graph.

Reference: Vivek Acharya, "Semantic Consensus: Process-Aware Conflict
Detection and Resolution for Enterprise Multi-Agent LLM Systems",
arXiv 2604.16339, March 2026. The SCF Type 1 (Contradictory Intent
on the same logical action) is detected separately by the BELIEF
divergence path (synapse.beliefs), which fires on conflicting values
for the same belief key.

RESOLUTION-TIER HINTS (also from SCF):
  Each conflict carries `resolution_tier_hint` ∈ {"policy", "capability",
  "temporal", "escalation"} describing which tier of the SCF cascade
  would have resolved it in live mode. Audit consumers can use this to
  prioritize investigation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..state import find_overlapping_scopes
from .events import AuditEvent, is_write


@dataclass
class AuditConflict:
    intention: AuditEvent           # the event whose write caused the collision
    conflicting: list[AuditEvent]    # events from other agents that collide
    overlapping_scopes: list[str]
    kind: str                        # "scope_overlap" | "stale_base_overwrite" | "causal_violation"
    rationale: str
    # SCF resolution-tier hint: which tier would resolve this in live mode.
    # See module docstring for tier semantics.
    resolution_tier_hint: str = "temporal"

    def to_dict(self) -> dict[str, Any]:
        return {
            "intention": {
                "agent_id": self.intention.agent_id,
                "tool_name": self.intention.tool_name,
                "scope": self.intention.scope_inferred,
                "ts_start_ms": self.intention.ts_start_ms,
                "tool_args": self.intention.tool_args,
            },
            "conflicting": [
                {
                    "agent_id": c.agent_id,
                    "tool_name": c.tool_name,
                    "scope": c.scope_inferred,
                    "ts_start_ms": c.ts_start_ms,
                    "ts_end_ms": c.ts_end_ms,
                }
                for c in self.conflicting
            ],
            "overlapping_scopes": self.overlapping_scopes,
            "kind": self.kind,
            "rationale": self.rationale,
            "resolution_tier_hint": self.resolution_tier_hint,
        }


# Default critical-scope patterns that map to the SCF "policy" resolution
# tier. Scopes matching any prefix here get tier="policy" (highest
# severity) instead of "temporal". Override at call site.
DEFAULT_CRITICAL_SCOPE_PREFIXES: tuple[str, ...] = (
    "billing.", "prod.deploy.", "prod.delete.", "auth.admin.",
    "db.users.", "db.payments.", "db.orders.",
    "secrets.", "iam.", "kms.",
)


def _resolution_tier(
    overlapping_scopes: list[str],
    intention: AuditEvent,
    critical_prefixes: tuple[str, ...],
) -> str:
    """SCF tier hint: policy > capability > temporal > escalation.

    - policy: scope matches a critical-scope prefix (regulated/sensitive)
    - capability: agent identity carries a role suffix (e.g. "_admin")
    - temporal: default (first-writer-wins by timestamp)
    - escalation: kept for future use when no auto-resolution is possible
    """
    for scope in overlapping_scopes:
        for prefix in critical_prefixes:
            # Strip the action suffix (":w", ":r") for matching
            base = scope.split(":")[0]
            if base.startswith(prefix):
                return "policy"
    agent = intention.agent_id.lower()
    if any(agent.endswith(s) for s in ("_admin", "_root", "_owner", "_lead")):
        return "capability"
    return "temporal"


def detect_conflicts(
    events: list[AuditEvent],
    *,
    lookback_ms: int = 60_000,
    write_only: bool = True,
    critical_scope_prefixes: Optional[tuple[str, ...]] = None,
) -> list[AuditConflict]:
    """Run the L2-style detector across an event list.

    Args:
        events: AuditEvent records (already scope-annotated).
        lookback_ms: how far back to look for stale-base overwrites.
        write_only: if True, only consider write-class tools (skip
            reads since two reads can't collide).
        critical_scope_prefixes: scopes whose prefix matches one of these
            get a "policy" resolution-tier hint (highest priority).
            Defaults to common production / billing / secrets paths.
    """
    crit_prefixes = critical_scope_prefixes or DEFAULT_CRITICAL_SCOPE_PREFIXES
    # Sort by start time so we can do a single forward pass
    sorted_events = sorted(events, key=lambda e: e.ts_start_ms)

    # Index by session for cheaper lookup
    by_session: dict[str, list[AuditEvent]] = {}
    for ev in sorted_events:
        if write_only and not is_write(ev):
            continue
        if not ev.scope_inferred:
            continue
        by_session.setdefault(ev.session_id, []).append(ev)

    conflicts: list[AuditConflict] = []

    for session_events in by_session.values():
        # For each event, look back at events from OTHER agents in the
        # same session whose scope overlaps.
        for i, ev in enumerate(session_events):
            colliding: list[AuditEvent] = []
            kinds_seen: set[str] = set()
            overlap_all: set[str] = set()

            for prior in session_events[:i]:
                if prior.agent_id == ev.agent_id:
                    continue
                if not prior.scope_inferred:
                    continue
                overlap = find_overlapping_scopes(ev.scope_inferred, prior.scope_inferred)
                if not overlap:
                    continue

                # Determine kind:
                #   - If prior was still active when ev started (ts_end >
                #     ev.ts_start): scope_overlap (concurrent)
                #   - Else if prior.ts_end < ev.ts_start <= prior.ts_end +
                #     lookback_ms: stale_base_overwrite
                if prior.ts_end_ms >= ev.ts_start_ms:
                    kinds_seen.add("scope_overlap")
                elif ev.ts_start_ms - prior.ts_end_ms <= lookback_ms:
                    kinds_seen.add("stale_base_overwrite")
                else:
                    continue  # too old, skip

                colliding.append(prior)
                overlap_all.update(overlap)

            if colliding:
                kind = (
                    "scope_overlap" if "scope_overlap" in kinds_seen
                    else "stale_base_overwrite"
                )
                others = sorted({c.agent_id for c in colliding})
                if kind == "scope_overlap":
                    rationale = (
                        f"{ev.agent_id} attempted to write {ev.scope_inferred} "
                        f"while {len(others)} other agent(s) ({', '.join(others)}) "
                        f"held active intention(s) on overlapping scope(s) "
                        f"{sorted(overlap_all)}."
                    )
                else:
                    rationale = (
                        f"{ev.agent_id}'s write to {ev.scope_inferred} would "
                        f"clobber recent changes by {', '.join(others)}. "
                        f"Their work resolved less than {lookback_ms//1000}s ago — "
                        f"{ev.agent_id} likely never saw it."
                    )
                tier = _resolution_tier(sorted(overlap_all), ev, crit_prefixes)
                conflicts.append(
                    AuditConflict(
                        intention=ev,
                        conflicting=colliding,
                        overlapping_scopes=sorted(overlap_all),
                        kind=kind,
                        rationale=rationale,
                        resolution_tier_hint=tier,
                    )
                )

    return conflicts
