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
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..state import find_overlapping_scopes
from .events import AuditEvent, is_write


@dataclass
class AuditConflict:
    intention: AuditEvent           # the event whose write caused the collision
    conflicting: list[AuditEvent]    # events from other agents that collide
    overlapping_scopes: list[str]
    kind: str                        # "scope_overlap" | "stale_base_overwrite"
    rationale: str

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
        }


def detect_conflicts(
    events: list[AuditEvent],
    *,
    lookback_ms: int = 60_000,
    write_only: bool = True,
) -> list[AuditConflict]:
    """Run the L2-style detector across an event list.

    Args:
        events: AuditEvent records (already scope-annotated).
        lookback_ms: how far back to look for stale-base overwrites.
        write_only: if True, only consider write-class tools (skip
            reads since two reads can't collide).
    """
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
                conflicts.append(
                    AuditConflict(
                        intention=ev,
                        conflicting=colliding,
                        overlapping_scopes=sorted(overlap_all),
                        kind=kind,
                        rationale=rationale,
                    )
                )

    return conflicts
