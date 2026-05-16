"""Synapse Agent — the developer-facing surface.

Phase 1 surface area: register, emit_intention (with optional pre-execution gate),
drain_inbox, emit_resolution. Decorator API (@agent.intention) lands in Phase 2
once we've validated the manual flow in the conflict demo.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional

# Note: ULID lives behind the [live] extras. Imported lazily by messages.py.
from synapse.adapters.base import InferenceAdapter
# Bus is also part of [live]; import lazily where used to keep audit-only
# imports cheap.
from synapse.bus import Bus
from synapse.messages import (
    AgentRegistration,
    Belief,
    Block,
    Conflict,
    ConflictingIntention,
    Envelope,
    Intention,
    MessageType,
    Resolution,
)
from synapse.state import StateGraph

logger = logging.getLogger(__name__)


# Pre-execution gate window per spec — if blocking=True, wait this long for
# CONFLICT/BLOCK signals before proceeding.
DEFAULT_GATE_MS = 50


class Agent:
    def __init__(
        self,
        *,
        id: str,
        session: str,
        backend: InferenceAdapter,
        subscribes: Optional[list[str]] = None,
        scopes_owned: Optional[list[str]] = None,
        tenant_id: Optional[str] = None,
        bus: Optional[Bus] = None,
        state: Optional[StateGraph] = None,
    ) -> None:
        self.id = id
        self.session = session
        self.backend = backend
        self.subscribes = subscribes or []
        self.scopes_owned = scopes_owned or []
        self.tenant_id = tenant_id
        self._bus = bus
        self._state = state
        self._inbox_cursor = "0"  # Drain everything from beginning on first read
        self._connected = False

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------
    @asynccontextmanager
    async def lifecycle(self):
        """Async context manager: connect bus + state, register, drain on exit."""
        await self._connect()
        try:
            await self._register()
            yield self
        finally:
            await self._disconnect()

    async def _connect(self) -> None:
        if self._bus is not None:
            if not getattr(self._bus, "_redis", None):
                await self._bus.connect()
        if self._state is not None:
            if not getattr(self._state, "_pool", None):
                await self._state.connect()
        self._connected = True

    async def _disconnect(self) -> None:
        # Lifecycle owners (the demo, the runtime) typically share the bus/state,
        # so we don't close them here. Just mark disconnected.
        self._connected = False

    async def _register(self) -> None:
        if self._state is None:
            return
        reg = AgentRegistration(
            agent_id=self.id,
            session_id=self.session,
            tenant_id=self.tenant_id,
            subscribes=self.subscribes,
            scopes_owned=self.scopes_owned,
            capabilities=self.backend.capabilities,
        )
        await self._state.register_agent(reg)

    # -----------------------------------------------------------------
    # Intention emission
    # -----------------------------------------------------------------
    async def emit_intention(
        self,
        *,
        action: dict[str, Any],
        scope: list[str],
        expected_outcome: str,
        blocking: bool = False,
        estimated_duration_ms: Optional[int] = None,
        uncertainty: Optional[str] = None,
        blocks_others: Optional[list[str]] = None,
        gate_ms: int = DEFAULT_GATE_MS,
    ) -> tuple[str, list[Conflict]]:
        """Emit an INTENTION and (if blocking) wait briefly for CONFLICT/BLOCK signals.

        Returns (intention_id, list_of_conflicts_received). If conflicts is non-empty
        and blocking=True, the caller should pivot/wait/abort instead of executing.

        Performance — active-scope fast path
        -------------------------------------
        After persisting our intention, we ourselves call ``find_conflicts``
        against the state graph to check for ANY currently-active intention
        on overlapping scopes. The result is authoritative because we just
        wrote our row, so any concurrent writer that committed before us is
        visible. If the result is empty we skip the gate window entirely —
        no need to wait ``gate_ms`` for the router to deliver the same
        empty answer via inbox.

        This drops no-conflict-path latency from ~80ms (full gate) to a
        single state round-trip (~3-5ms in zero-infra mode, ~5-15ms in
        live mode). When a conflict IS detected the gate window still runs
        as a fallback to pick up router-emitted CONFLICTs that arrive
        slightly later (e.g. tier hint and rationale enrichment).
        """
        if self._bus is None or self._state is None:
            raise RuntimeError("Agent requires a Bus and StateGraph for emit_intention")

        intention = Intention(
            action=action,
            scope=scope,
            expected_outcome=expected_outcome,
            blocking=blocking,
            estimated_duration_ms=estimated_duration_ms,
            uncertainty=uncertainty,
            blocks_others=blocks_others or [],
        )
        envelope = Envelope.make(
            type=MessageType.INTENTION,
            agent_id=self.id,
            session_id=self.session,
            payload=intention,
            tenant_id=self.tenant_id,
        )

        # 1. Persist to state graph FIRST so the router sees it on lookup
        #    AND so our self-check below sees it (we filter by id != ours).
        await self._state.insert_intention(
            intention_id=envelope.msg_id,
            agent_id=self.id,
            session_id=self.session,
            tenant_id=self.tenant_id,
            intention=intention,
        )

        # 2. Publish to session stream so the router worker picks it up.
        await self._bus.publish_session(envelope)

        conflicts: list[Conflict] = []

        # 3a. Fast path: immediate self-check for active + recently-resolved
        #     conflicts. Authoritative because our row is already in the
        #     state graph, so any concurrent writer that committed before
        #     us is visible. Uses the same default lookback as the router
        #     so stale-base-overwrite scenarios surface here too — the
        #     fast path is a strict superset of the gate window's coverage.
        if blocking:
            try:
                rows = await self._state.find_conflicts(
                    new_intention_id=envelope.msg_id,
                    agent_id=self.id,
                    session_id=self.session,
                    scope=scope,
                    resolved_lookback_ms=60_000,
                )
            except Exception as e:
                logger.warning("emit_intention: find_conflicts failed (%s); falling back to gate", e)
                rows = None

            if rows is not None and not rows:
                # v0.2.7 fix (Phase 7b/8 finding): in concurrent multi-agent
                # scenarios (3+ agents claiming the same scope within ~ms),
                # agent A's find_conflicts() may run BEFORE agents B and C
                # have committed their rows — so we'd miss their concurrent
                # claims and the fast-path would return [] for everyone, but
                # the router (which sees the bus stream globally) would
                # emit CONFLICTs to the contenders.
                #
                # To make 3-agent CONFLICT routing deterministic, still drain
                # the inbox briefly for router-emitted CONFLICTs even when our
                # local fast-path query returns []. Latency cost: up to
                # gate_ms (default 50ms) per concurrent claim, only when
                # blocking=True. Callers who want zero latency can pass
                # blocking=False or gate_ms=0.
                if blocking and gate_ms > 0:
                    router_conflicts = await self._wait_for_signals(
                        envelope.msg_id, window_ms=gate_ms,
                    )
                    if router_conflicts:
                        return envelope.msg_id, router_conflicts
                return envelope.msg_id, []

            if rows:
                # Synthesize Conflict envelopes from the rows so the
                # caller (intend()) can apply MergePolicy without waiting
                # for the router's inbox delivery. Same shape as router
                # output (see runtime/router/worker._emit_conflict).
                #
                # Match the router's kind-selection logic exactly so
                # downstream MergePolicies that switch on kind (e.g.
                # queue_behind for active vs. retry for stale-base) get
                # the right branch in fast-path mode.
                cis: list[ConflictingIntention] = []
                overlapping_all: set[str] = set()
                active_count = 0
                recent_count = 0
                for r in rows:
                    cis.append(ConflictingIntention(
                        intention_id=r["intention_id"],
                        agent_id=r["agent_id"],
                        scope=r["scope"],
                        started_at_ms=r["started_at_ms"],
                    ))
                    overlapping_all.update(r["overlapping_scopes"])
                    if r.get("kind") == "active":
                        active_count += 1
                    elif r.get("kind") == "recent_resolution":
                        recent_count += 1

                kind_str = (
                    "scope_overlap" if active_count > 0
                    else "stale_base_overwrite"
                )
                if active_count and recent_count:
                    rationale = (
                        f"Your intention's scope {scope} overlaps with "
                        f"{active_count} active and {recent_count} "
                        f"recently-resolved intention(s) by other agent(s)."
                    )
                elif active_count:
                    rationale = (
                        f"Your intention's scope {scope} overlaps with "
                        f"{active_count} active intention(s) by other agent(s)."
                    )
                else:
                    rationale = (
                        f"Your intention's scope {scope} was just modified "
                        f"by {recent_count} other agent(s) — your write "
                        f"would clobber their changes unless you pull first."
                    )
                synthetic_conflict = Conflict(
                    intention_id=envelope.msg_id,
                    conflicting_intentions=cis,
                    kind=kind_str,
                    overlapping_scopes=sorted(overlapping_all),
                    suggested_resolution="pivot",
                    rationale=rationale,
                )
                conflicts.append(synthetic_conflict)
                # v0.2.10 fix: ALSO publish the CONFLICT envelope to the
                # session stream so external auditors / observability
                # dashboards can find it without reaching into per-agent
                # inboxes. The fast path used to short-circuit and never
                # publish CONFLICT to the session stream — measurement
                # scripts relying on the session log saw 0 conflicts even
                # under live W↔W overlap. Match the L2 router worker's
                # two-channel pattern (inbox for resolution + session for
                # audit).
                try:
                    conflict_env = Envelope.make(
                        type=MessageType.CONFLICT,
                        agent_id="router_local",  # in-process emitter id
                        session_id=self.session,
                        payload=synthetic_conflict,
                        parent_msg_id=envelope.msg_id,
                        tenant_id=self.tenant_id,
                    )
                    await self._bus.publish_session(conflict_env)
                except Exception as e:
                    logger.warning(
                        "agent.emit_intention: publish_session(CONFLICT) "
                        "failed (%s); audit log will miss this CONFLICT", e,
                    )
                # Also briefly check the inbox in case the router has
                # already enriched a CONFLICT with tier/rationale.
                router_conflicts = await self._wait_for_signals(
                    envelope.msg_id, window_ms=min(gate_ms, 50)
                )
                if router_conflicts:
                    # Router-emitted version is richer (resolution_tier,
                    # cross-process info) — prefer it over our synthetic.
                    conflicts = router_conflicts

        return envelope.msg_id, conflicts

    async def _wait_for_signals(
        self, intention_id: str, window_ms: int
    ) -> list[Conflict]:
        """Drain inbox during the gate window, return any CONFLICT/BLOCK targeting this intention."""
        deadline = asyncio.get_running_loop().time() + window_ms / 1000
        out: list[Conflict] = []
        while asyncio.get_running_loop().time() < deadline:
            entries = await self._bus.drain_inbox(self.id, last_id=self._inbox_cursor)
            for entry_id, env in entries:
                self._inbox_cursor = entry_id
                if env.type == MessageType.CONFLICT:
                    conflict = Conflict.model_validate(env.payload)
                    if conflict.intention_id == intention_id:
                        out.append(conflict)
            if out:
                break
            await asyncio.sleep(0.01)
        return out

    # -----------------------------------------------------------------
    # Resolution
    # -----------------------------------------------------------------
    async def emit_resolution(
        self,
        *,
        intention_id: str,
        outcome: str = "success",
        state_diff: Optional[dict[str, Any]] = None,
        side_effects: Optional[list[str]] = None,
    ) -> str:
        if self._bus is None or self._state is None:
            raise RuntimeError("Agent requires a Bus and StateGraph for emit_resolution")
        await self._state.resolve_intention(intention_id)
        resolution = Resolution(
            intention_id=intention_id,
            outcome=outcome,  # type: ignore[arg-type]
            state_diff=state_diff or {},
            side_effects=side_effects or [],
        )
        envelope = Envelope.make(
            type=MessageType.RESOLUTION,
            agent_id=self.id,
            session_id=self.session,
            payload=resolution,
            parent_msg_id=intention_id,
            tenant_id=self.tenant_id,
        )
        await self._bus.publish_session(envelope)
        return envelope.msg_id

    # -----------------------------------------------------------------
    # Belief / Block emission
    # -----------------------------------------------------------------
    async def emit_belief(
        self,
        *,
        key: str,
        value: Any,
        confidence: float = 0.9,
        source: str = "observed",
        evidence: Optional[str] = None,
    ) -> str:
        """Emit a BELIEF. The coordinator persists and runs divergence detection."""
        if self._bus is None:
            raise RuntimeError("Agent requires a Bus for emit_belief")
        belief = Belief(
            key=key, value=value, confidence=confidence,
            source=source, evidence=evidence,  # type: ignore[arg-type]
        )
        env = Envelope.make(
            type=MessageType.BELIEF,
            agent_id=self.id,
            session_id=self.session,
            payload=belief,
            tenant_id=self.tenant_id,
        )
        await self._bus.publish_session(env)
        return env.msg_id

    async def emit_block(
        self,
        *,
        blocker: str,
        needed: str,
        attempted: Optional[list[str]] = None,
        urgency: str = "medium",
        topics: Optional[list[str]] = None,
    ) -> str:
        """Emit a BLOCK signal. Coordinator routes to capable peers and
        synthesizes guidance via LLM if available."""
        if self._bus is None:
            raise RuntimeError("Agent requires a Bus for emit_block")
        block = Block(
            blocker=blocker, needed=needed,
            attempted=attempted or [],
            urgency=urgency,  # type: ignore[arg-type]
            topics=topics or [],
        )
        env = Envelope.make(
            type=MessageType.BLOCK,
            agent_id=self.id,
            session_id=self.session,
            payload=block,
            tenant_id=self.tenant_id,
        )
        await self._bus.publish_session(env)
        return env.msg_id

    async def wait_for_signal(
        self, *, types: Optional[list[MessageType]] = None, timeout_s: float = 5.0
    ) -> Optional[Envelope]:
        """Drain inbox until a signal of the given type(s) arrives or timeout.

        Returns the first matching envelope or None on timeout.
        """
        if self._bus is None:
            return None
        deadline = asyncio.get_running_loop().time() + timeout_s
        types_set = set(types) if types else None
        while asyncio.get_running_loop().time() < deadline:
            entries = await self._bus.drain_inbox(self.id, last_id=self._inbox_cursor)
            for entry_id, env in entries:
                self._inbox_cursor = entry_id
                if types_set is None or env.type in types_set:
                    return env
            await asyncio.sleep(0.05)
        return None

    # -----------------------------------------------------------------
    # Inbox helpers
    # -----------------------------------------------------------------
    async def drain_signals(self) -> list[Envelope]:
        """Read all inbox messages since last drain. Returns envelopes (caller dispatches by type)."""
        if self._bus is None:
            return []
        entries = await self._bus.drain_inbox(self.id, last_id=self._inbox_cursor)
        for entry_id, _ in entries:
            self._inbox_cursor = entry_id
        return [env for _, env in entries]
