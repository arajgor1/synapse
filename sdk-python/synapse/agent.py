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

from ulid import ULID

from synapse.adapters.base import InferenceAdapter
from synapse.bus import Bus
from synapse.messages import (
    AgentRegistration,
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

        # 1. Persist to state graph FIRST so the router sees it on lookup.
        await self._state.insert_intention(
            intention_id=envelope.msg_id,
            agent_id=self.id,
            session_id=self.session,
            tenant_id=self.tenant_id,
            intention=intention,
        )

        # 2. Publish to session stream so the router worker picks it up.
        await self._bus.publish_session(envelope)

        # 3. If blocking, wait the gate window for CONFLICT/BLOCK signals.
        conflicts: list[Conflict] = []
        if blocking:
            conflicts = await self._wait_for_signals(
                envelope.msg_id, window_ms=gate_ms
            )

        return envelope.msg_id, conflicts

    async def _wait_for_signals(
        self, intention_id: str, window_ms: int
    ) -> list[Conflict]:
        """Drain inbox during the gate window, return any CONFLICT/BLOCK targeting this intention."""
        deadline = asyncio.get_event_loop().time() + window_ms / 1000
        out: list[Conflict] = []
        while asyncio.get_event_loop().time() < deadline:
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
