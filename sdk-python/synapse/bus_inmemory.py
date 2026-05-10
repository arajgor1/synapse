"""In-memory implementation of the Bus protocol for zero-infra mode.

Most users coming to Synapse for the first time don't have Redis running
and don't want to. Without a bus, ``synapse.install()`` falls back to
"offline mode" which silently disables coordination — the worst onboarding
cliff in the project. This module fixes that.

Surface match
-------------
``InMemoryBus`` exposes the same async methods as ``synapse.bus.Bus`` so
``synapse.agent.Agent`` and ``synapse.intend()`` work against it
unchanged: ``connect``, ``close``, ``publish_session``, ``publish_inbox``,
``ensure_group``, ``consume_group`` (async generator), ``consume_inbox``
(async generator), ``drain_inbox``, ``ack``.

Wire format mirrors Redis Streams:
  * Each stream is a list of ``(entry_id, fields_dict)`` tuples.
  * Entry IDs are monotonic ``"<seq>-0"`` strings (Redis-compatible).
  * Consumer groups track per-(group, consumer) cursors with at-least-
    once delivery semantics.
  * ``ack`` is a no-op for in-memory (cursor advances on read, like xread
    rather than xreadgroup pending lists). This is safe because zero-infra
    mode runs exactly ONE router consumer per session in-process, so we
    don't need pending-message redelivery.

Process scope
-------------
This bus is **single-process only**. Two Python processes both calling
``synapse.install()`` in zero-infra mode will each get their own
InMemoryBus and never see each other's events. For multi-process
coordination, set ``SYNAPSE_REDIS_URL`` and switch to the Redis Bus.
This limitation is documented in the install log so the user knows.

Memory bounds
-------------
Streams are bounded by ``maxlen`` (default 10_000 entries — same as the
Redis Bus). Old entries are dropped FIFO. Inbox streams are bounded too,
but inbox consumers typically drain promptly so the bound rarely bites.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any, AsyncIterator, Optional

from synapse.messages import Envelope

logger = logging.getLogger(__name__)


def session_stream(session_id: str) -> str:
    return f"synapse:session:{session_id}:events"


def agent_inbox(agent_id: str) -> str:
    return f"synapse:agent:{agent_id}:inbox"


DEFAULT_MAXLEN = 10_000


class InMemoryBus:
    """Drop-in replacement for ``synapse.bus.Bus`` that requires no infra.

    Backed by ``deque``s + ``asyncio.Event``s for wakeup; one event per
    stream coalesces signals so a busy producer doesn't pile up wakeups.
    """

    def __init__(self, *, maxlen: int = DEFAULT_MAXLEN) -> None:
        self._maxlen = maxlen
        # stream_name -> deque of (entry_id, fields)
        self._streams: dict[str, deque[tuple[str, dict[str, str]]]] = {}
        # stream_name -> Condition used to broadcast wakeups. Per-stream
        # Condition (broadcast via notify_all) replaces the previous
        # per-stream Event pattern that lost wakeups when multiple
        # consumers waited on the same stream — a real risk now that the
        # in-process Router and Agent inbox listeners can both watch
        # the same session stream in zero-infra mode (audit finding A1).
        self._conds: dict[str, asyncio.Condition] = {}
        # (stream, group, consumer) -> last delivered seq (int)
        self._group_cursors: dict[tuple[str, str, str], int] = {}
        # Monotonic sequence used to mint Redis-compatible entry IDs.
        self._seq = 0
        self._lock = asyncio.Lock()
        self._closed = False

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------
    async def connect(self) -> None:
        # Nothing to do — kept for protocol parity with the Redis Bus.
        logger.info("InMemoryBus connected (zero-infra mode, single-process only)")

    async def close(self) -> None:
        self._closed = True
        # Broadcast on every condition so all consumers wake and observe
        # the close. notify_all wakes every waiter (vs Event.set which
        # only wakes whoever is currently awaiting + races with concurrent
        # clears).
        for cond in list(self._conds.values()):
            try:
                async with cond:
                    cond.notify_all()
            except Exception:
                pass

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------
    def _ensure_stream(self, name: str) -> None:
        if name not in self._streams:
            self._streams[name] = deque(maxlen=self._maxlen)
            self._conds[name] = asyncio.Condition()

    def _next_id(self) -> str:
        # Redis xadd entry IDs are strings like "<ms-timestamp>-<seq>".
        # We don't need the timestamp; a monotonic seq is enough and keeps
        # downstream parsing trivial.
        self._seq += 1
        return f"{self._seq}-0"

    def _seq_of(self, entry_id: str) -> int:
        try:
            return int(entry_id.split("-", 1)[0])
        except Exception:
            return 0

    # -----------------------------------------------------------------
    # Publish
    # -----------------------------------------------------------------
    async def publish_session(self, envelope: Envelope) -> str:
        return await self._xadd(session_stream(envelope.session_id), envelope)

    async def publish_inbox(self, agent_id: str, envelope: Envelope) -> str:
        return await self._xadd(agent_inbox(agent_id), envelope)

    async def _xadd(self, stream: str, envelope: Envelope) -> str:
        async with self._lock:
            self._ensure_stream(stream)
            entry_id = self._next_id()
            self._streams[stream].append((entry_id, {"e": envelope.model_dump_json()}))
            cond = self._conds[stream]
        # Broadcast under the Condition's lock so every waiter on this
        # stream wakes up. notify_all (vs Event.set) avoids the lost-
        # wakeup race when multiple consumers share the stream — e.g.
        # the in-process Router AND an Agent inbox listener both
        # tailing the same session in zero-infra mode.
        async with cond:
            cond.notify_all()
        return entry_id

    # -----------------------------------------------------------------
    # Consumer-group reads (at-least-once, single consumer per group OK)
    # -----------------------------------------------------------------
    async def ensure_group(self, stream: str, group: str) -> None:
        async with self._lock:
            self._ensure_stream(stream)
            # No persistent group state needed beyond the cursor map; the
            # cursor lazily initialises on first consume_group call.

    async def consume_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        block_ms: int = 1000,
        count: int = 32,
    ) -> AsyncIterator[tuple[str, Envelope]]:
        await self.ensure_group(stream, group)
        key = (stream, group, consumer)
        self._group_cursors.setdefault(key, 0)
        while not self._closed:
            # Snapshot under the lock; deliver outside the lock.
            async with self._lock:
                self._ensure_stream(stream)
                cursor = self._group_cursors[key]
                pending: list[tuple[str, dict[str, str]]] = []
                for entry_id, fields in self._streams[stream]:
                    if self._seq_of(entry_id) > cursor:
                        pending.append((entry_id, fields))
                        if len(pending) >= count:
                            break
                if pending:
                    self._group_cursors[key] = self._seq_of(pending[-1][0])
                cond = self._conds[stream]

            if not pending:
                # Wait on the per-stream Condition. notify_all from xadd
                # wakes every consumer; each then re-checks its cursor.
                # No lost-wakeup race like the prior Event-based pattern.
                async with cond:
                    try:
                        await asyncio.wait_for(
                            cond.wait(), timeout=block_ms / 1000.0
                        )
                    except asyncio.TimeoutError:
                        pass
                continue

            for entry_id, fields in pending:
                try:
                    yield entry_id, Envelope.model_validate_json(fields["e"])
                except Exception as e:
                    logger.error("InMemoryBus: bad envelope %s (%s)", entry_id, e)

    async def ack(self, stream: str, group: str, entry_id: str) -> None:
        # No-op: in-memory bus advances the cursor on delivery in
        # consume_group rather than maintaining a separate pending list.
        # Documented at module level — see "ack is a no-op" note.
        return None

    # -----------------------------------------------------------------
    # Inbox reads (single-consumer, caller tracks last_id)
    # -----------------------------------------------------------------
    async def consume_inbox(
        self,
        agent_id: str,
        last_id: str = "$",
        block_ms: int = 1000,
        count: int = 32,
    ) -> AsyncIterator[tuple[str, Envelope]]:
        stream = agent_inbox(agent_id)
        # Redis convention: "$" means "only deliver entries that arrive
        # AFTER this consumer attaches". The per-stream high-water mark
        # comes from the last entry in THIS stream — using the global
        # ``self._seq`` (the previous A2 bug) drifted from Redis
        # semantics when other streams had recent activity.
        if last_id == "$":
            async with self._lock:
                self._ensure_stream(stream)
                last_seq = (
                    self._seq_of(self._streams[stream][-1][0])
                    if self._streams[stream] else 0
                )
        else:
            last_seq = self._seq_of(last_id)

        while not self._closed:
            async with self._lock:
                self._ensure_stream(stream)
                pending = [
                    (eid, f) for eid, f in self._streams[stream]
                    if self._seq_of(eid) > last_seq
                ][:count]
                if pending:
                    last_seq = self._seq_of(pending[-1][0])
                cond = self._conds[stream]

            if not pending:
                async with cond:
                    try:
                        await asyncio.wait_for(
                            cond.wait(), timeout=block_ms / 1000.0
                        )
                    except asyncio.TimeoutError:
                        pass
                continue

            for entry_id, fields in pending:
                try:
                    yield entry_id, Envelope.model_validate_json(fields["e"])
                except Exception as e:
                    logger.error("InMemoryBus: bad inbox envelope %s (%s)", entry_id, e)

    async def drain_inbox(
        self, agent_id: str, last_id: str = "0"
    ) -> list[tuple[str, Envelope]]:
        """Non-blocking: read all available inbox messages since last_id."""
        stream = agent_inbox(agent_id)
        out: list[tuple[str, Envelope]] = []
        last_seq = self._seq_of(last_id)
        async with self._lock:
            self._ensure_stream(stream)
            for entry_id, fields in self._streams[stream]:
                if self._seq_of(entry_id) > last_seq:
                    try:
                        out.append((entry_id, Envelope.model_validate_json(fields["e"])))
                    except Exception as e:
                        logger.error("InMemoryBus: bad inbox envelope %s (%s)", entry_id, e)
        return out
