"""Redis Streams client for the Synapse message bus.

Conventions:
- Session-wide stream: synapse:session:{session_id}:events
- Per-agent inbox stream: synapse:agent:{agent_id}:inbox
- Consumer group for the router: 'router' on the session stream
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Optional

# redis lives behind the [live] extras. Audit-only installs don't need it
# and shouldn't crash on import. Tolerate the missing dep here; raise a
# clean error in Bus.connect() if someone tries to use it without [live].
try:
    import redis.asyncio as aioredis  # type: ignore[import-not-found]
    _REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover — exercised in audit-only installs
    aioredis = None  # type: ignore[assignment]
    _REDIS_AVAILABLE = False


def _require_redis() -> None:
    if not _REDIS_AVAILABLE:
        raise ImportError(
            "synapse.bus requires the 'live' extras. Install with "
            "`pip install synapse-protocol[live]`. The `synapse audit` "
            "subcommand and read-only audit pipeline do NOT need this."
        )


from synapse.messages import Envelope

logger = logging.getLogger(__name__)


def session_stream(session_id: str) -> str:
    return f"synapse:session:{session_id}:events"


def agent_inbox(agent_id: str) -> str:
    return f"synapse:agent:{agent_id}:inbox"


# Keep streams bounded so dev-mode Redis doesn't grow unbounded.
DEFAULT_MAXLEN = 10_000


class Bus:
    """Async Redis Streams wrapper with envelope serialization."""

    def __init__(self, url: str = "redis://localhost:6379/0") -> None:
        self._url = url
        self._redis: Optional[aioredis.Redis] = None

    async def connect(self) -> None:
        _require_redis()
        self._redis = aioredis.from_url(self._url, decode_responses=True)
        await self._redis.ping()
        logger.info("Bus connected: %s", self._url)

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    @property
    def redis(self) -> aioredis.Redis:
        if self._redis is None:
            raise RuntimeError("Bus not connected. Call connect() first.")
        return self._redis

    async def publish_session(self, envelope: Envelope) -> str:
        """Publish to the session-wide stream. Returns the Redis stream entry ID."""
        stream = session_stream(envelope.session_id)
        return await self._xadd(stream, envelope)

    async def publish_inbox(self, agent_id: str, envelope: Envelope) -> str:
        """Publish directly to a specific agent's inbox."""
        stream = agent_inbox(agent_id)
        return await self._xadd(stream, envelope)

    async def _xadd(self, stream: str, envelope: Envelope) -> str:
        payload = envelope.model_dump_json()
        return await self.redis.xadd(
            stream,
            {"e": payload},
            maxlen=DEFAULT_MAXLEN,
            approximate=True,
        )

    async def ensure_group(self, stream: str, group: str) -> None:
        """Idempotently create a consumer group at the start of the stream."""
        try:
            await self.redis.xgroup_create(stream, group, id="0", mkstream=True)
            logger.info("Created consumer group %s on %s", group, stream)
        except aioredis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
            # Group already exists — fine.

    async def consume_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        block_ms: int = 1000,
        count: int = 32,
    ) -> AsyncIterator[tuple[str, Envelope]]:
        """Long-running consumer group reader. Yields (entry_id, envelope) tuples."""
        await self.ensure_group(stream, group)
        while True:
            try:
                resp = await self.redis.xreadgroup(
                    groupname=group,
                    consumername=consumer,
                    streams={stream: ">"},
                    count=count,
                    block=block_ms,
                )
            except aioredis.ConnectionError:
                logger.warning("Bus connection error; retrying...")
                await self._sleep(0.5)
                continue
            if not resp:
                continue
            for _, entries in resp:
                for entry_id, fields in entries:
                    try:
                        envelope = Envelope.model_validate_json(fields["e"])
                        yield entry_id, envelope
                    except Exception as e:
                        logger.error("Failed to parse envelope %s: %s", entry_id, e)
                        # Acknowledge bad entries so they don't block the stream.
                        await self.redis.xack(stream, group, entry_id)

    async def ack(self, stream: str, group: str, entry_id: str) -> None:
        await self.redis.xack(stream, group, entry_id)

    async def consume_inbox(
        self,
        agent_id: str,
        last_id: str = "$",
        block_ms: int = 1000,
        count: int = 32,
    ) -> AsyncIterator[tuple[str, Envelope]]:
        """Single-consumer inbox reader. Caller tracks last_id."""
        stream = agent_inbox(agent_id)
        while True:
            try:
                resp = await self.redis.xread(
                    streams={stream: last_id},
                    count=count,
                    block=block_ms,
                )
            except aioredis.ConnectionError:
                logger.warning("Bus connection error; retrying...")
                await self._sleep(0.5)
                continue
            if not resp:
                continue
            for _, entries in resp:
                for entry_id, fields in entries:
                    last_id = entry_id
                    try:
                        envelope = Envelope.model_validate_json(fields["e"])
                        yield entry_id, envelope
                    except Exception as e:
                        logger.error("Failed to parse inbox envelope %s: %s", entry_id, e)

    async def drain_inbox(self, agent_id: str, last_id: str = "0") -> list[tuple[str, Envelope]]:
        """Non-blocking: read all available inbox messages since last_id and return them.

        IMPORTANT: redis-py's xread() treats block=None as non-blocking and
        block=0 as 'block forever'. We pass block=None so an empty inbox
        returns immediately rather than hanging until a new message arrives.
        """
        stream = agent_inbox(agent_id)
        resp = await self.redis.xread(streams={stream: last_id}, count=1000, block=None)
        out: list[tuple[str, Envelope]] = []
        if not resp:
            return out
        for _, entries in resp:
            for entry_id, fields in entries:
                try:
                    out.append((entry_id, Envelope.model_validate_json(fields["e"])))
                except Exception as e:
                    logger.error("Failed to parse inbox envelope %s: %s", entry_id, e)
        return out

    @staticmethod
    async def _sleep(seconds: float) -> None:
        import asyncio
        await asyncio.sleep(seconds)
