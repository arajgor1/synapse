"""In-process L2 conflict router for zero-infra mode.

In a real deployment, ``runtime/router/worker.py`` runs as a separate
process consuming the session stream and emitting CONFLICT envelopes
to agent inboxes. That separate-process design exists so the router
can scale independently and survive agent crashes.

For zero-infra mode (``synapse.install()`` with no Redis/Postgres) we
don't have a separate process. This module is a lightweight in-process
equivalent that runs inside the user's asyncio loop. Same logic as
the standalone router, just without the deployment overhead.

One router task per (session, bus) pair. Started lazily by
``synapse.intend._ensure_connected`` when the first agent in a session
is created in zero-infra mode. Stopped on ``synapse.intend.shutdown``.

Design constraint: must not import from ``runtime/`` because that
directory isn't part of the installed ``synapse-protocol`` wheel.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from synapse.messages import (
    Conflict,
    ConflictingIntention,
    Envelope,
    Intention,
    MessageType,
)

logger = logging.getLogger(__name__)


CONSUMER_GROUP = "router"


def _session_stream(session_id: str) -> str:
    return f"synapse:session:{session_id}:events"


class InProcessRouter:
    """L2 router. Identical semantics to runtime/router/worker.Router but
    runs inside the user's process, holds no separate connections, and
    works against either Bus implementation (Redis or in-memory)."""

    def __init__(self, bus: Any, state: Any, session_id: str) -> None:
        self.bus = bus
        self.state = state
        self.session_id = session_id
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(
            self._run_loop(), name=f"synapse-router:{self.session_id}"
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is None:
            return
        # 1. Wait briefly for the natural exit path (consume_group sees
        #    self._stop on its next yield).
        try:
            await asyncio.wait_for(self._task, timeout=2.0)
            self._task = None
            return
        except asyncio.TimeoutError:
            pass
        except asyncio.CancelledError:
            self._task = None
            return
        # 2. Force cancellation, then AWAIT the cancellation to actually
        #    propagate. The previous version called .cancel() and dropped
        #    the task — leaked tasks could still be reading the (now
        #    closed) bus, mutating fresh runtimes between tests, or
        #    spamming errors after shutdown.
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):
            pass
        self._task = None

    async def _run_loop(self) -> None:
        stream = _session_stream(self.session_id)
        try:
            await self.bus.ensure_group(stream, CONSUMER_GROUP)
        except Exception as e:
            logger.warning("router: ensure_group failed (%s); will still consume", e)

        consumer = "inproc-1"
        try:
            async for entry_id, env in self.bus.consume_group(
                stream=stream,
                group=CONSUMER_GROUP,
                consumer=consumer,
                block_ms=500,
            ):
                if self._stop.is_set():
                    break
                try:
                    await self._dispatch(env)
                except Exception:
                    logger.exception("router: error processing %s", env.msg_id)
                finally:
                    try:
                        await self.bus.ack(stream, CONSUMER_GROUP, entry_id)
                    except Exception:
                        pass
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("router: consume loop crashed")

    async def _dispatch(self, env: Envelope) -> None:
        if env.type != MessageType.INTENTION:
            return
        intention = Intention.model_validate(env.payload)

        rows = await self.state.find_conflicts(
            new_intention_id=env.msg_id,
            agent_id=env.agent_id,
            session_id=env.session_id,
            scope=intention.scope,
        )
        if rows:
            await self._emit_conflict(env, intention, rows)

    async def _emit_conflict(
        self, env: Envelope, intention: Intention, conflicts: list[dict]
    ) -> None:
        overlapping_all: set[str] = set()
        cis: list[ConflictingIntention] = []
        for c in conflicts:
            cis.append(
                ConflictingIntention(
                    intention_id=c["intention_id"],
                    agent_id=c["agent_id"],
                    scope=c["scope"],
                    started_at_ms=c["started_at_ms"],
                )
            )
            overlapping_all.update(c["overlapping_scopes"])

        active_count = sum(1 for c in conflicts if c.get("kind") == "active")
        recent_count = sum(1 for c in conflicts if c.get("kind") == "recent_resolution")
        kind_str = "scope_overlap" if active_count > 0 else "stale_base_overwrite"
        if active_count and recent_count:
            rationale = (
                f"Your intention's scope {intention.scope} overlaps with "
                f"{active_count} active and {recent_count} recently-resolved "
                f"intention(s) by other agent(s)."
            )
        elif active_count:
            rationale = (
                f"Your intention's scope {intention.scope} overlaps with "
                f"{active_count} active intention(s) by other agent(s)."
            )
        else:
            rationale = (
                f"Your intention's scope {intention.scope} was just modified "
                f"by {recent_count} other agent(s) — your write would clobber "
                f"their changes unless you pull first."
            )

        conflict_payload = Conflict(
            intention_id=env.msg_id,
            conflicting_intentions=cis,
            kind=kind_str,
            overlapping_scopes=sorted(overlapping_all),
            suggested_resolution="pivot",
            rationale=rationale,
        )
        conflict_env = Envelope.make(
            type=MessageType.CONFLICT,
            agent_id="router",
            session_id=env.session_id,
            payload=conflict_payload,
            parent_msg_id=env.msg_id,
            tenant_id=env.tenant_id,
        )
        await self.bus.publish_inbox(env.agent_id, conflict_env)
        logger.warning(
            "synapse.router: CONFLICT (%s) routed to %s: intention=%s "
            "overlaps with %d intention(s) on scopes %s",
            kind_str, env.agent_id, env.msg_id, len(cis),
            sorted(overlapping_all),
        )
