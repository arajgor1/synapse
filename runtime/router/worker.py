"""Router worker.

Consumes a session stream via consumer group 'router'. For each INTENTION:
- L1: topic-glob subscription matching to other agents in session (informational fan-out)
- L2: scope-overlap conflict detection via the StateGraph

When a CONFLICT is detected, emit a CONFLICT envelope to the offending agent's inbox.

Failure mode: if Postgres is unreachable, log and skip (fail-open).
"""

from __future__ import annotations

import argparse
import asyncio
import fnmatch
import logging
import os
import signal
from typing import Optional

import asyncpg

from synapse.bus import Bus, agent_inbox, session_stream
from synapse.messages import (
    Conflict,
    ConflictingIntention,
    Envelope,
    Intention,
    MessageType,
)
from synapse.state import StateGraph

logger = logging.getLogger("synapse.router")


CONSUMER_GROUP = "router"


def topic_matches(topic: str, pattern: str) -> bool:
    """Glob-style topic matching (auth.* matches auth.middleware)."""
    return fnmatch.fnmatchcase(topic, pattern)


class Router:
    def __init__(self, bus: Bus, state: StateGraph, session_id: str, consumer: str = "r1") -> None:
        self.bus = bus
        self.state = state
        self.session_id = session_id
        self.consumer = consumer
        self._stop = asyncio.Event()

    async def run(self) -> None:
        stream = session_stream(self.session_id)
        await self.bus.ensure_group(stream, CONSUMER_GROUP)
        logger.info("Router started for session=%s consumer=%s", self.session_id, self.consumer)

        async for entry_id, env in self.bus.consume_group(
            stream=stream,
            group=CONSUMER_GROUP,
            consumer=self.consumer,
        ):
            try:
                await self._dispatch(env)
            except Exception:
                logger.exception("Router error processing %s", env.msg_id)
            finally:
                await self.bus.ack(stream, CONSUMER_GROUP, entry_id)
            if self._stop.is_set():
                break

    def stop(self) -> None:
        self._stop.set()

    async def _dispatch(self, env: Envelope) -> None:
        if env.type == MessageType.INTENTION:
            await self._handle_intention(env)
        # Phase 1 only handles INTENTION. PIVOT, BLOCK, RESOLUTION dispatch in later phases.

    async def _handle_intention(self, env: Envelope) -> None:
        intention = Intention.model_validate(env.payload)

        # L2: conflict detection
        rows = await self.state.find_conflicts(
            new_intention_id=env.msg_id,
            agent_id=env.agent_id,
            session_id=env.session_id,
            scope=intention.scope,
        )

        if rows:
            await self._emit_conflict(env, intention, rows)
        else:
            logger.info(
                "INTENTION %s by %s scope=%s — no conflicts",
                env.msg_id, env.agent_id, intention.scope,
            )

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

        conflict_payload = Conflict(
            intention_id=env.msg_id,
            conflicting_intentions=cis,
            kind="scope_overlap",
            overlapping_scopes=sorted(overlapping_all),
            suggested_resolution="pivot",
            rationale=(
                f"Your intention's scope {intention.scope} overlaps with "
                f"{len(cis)} active intention(s) by other agent(s)."
            ),
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
            "CONFLICT routed to %s: intention=%s overlaps with %d active intention(s) on scopes %s",
            env.agent_id, env.msg_id, len(cis), sorted(overlapping_all),
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main(session_id: str, redis_url: str, postgres_dsn: str, consumer: str) -> None:
    logging.basicConfig(
        level=os.getenv("SYNAPSE_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    bus = Bus(redis_url)
    state = StateGraph(postgres_dsn)
    await bus.connect()
    await state.connect()

    router = Router(bus, state, session_id, consumer)

    loop = asyncio.get_running_loop()
    # Best-effort signal handler (Windows: SIGTERM not available, so guard).
    for sig in (signal.SIGINT,) + (
        (signal.SIGTERM,) if hasattr(signal, "SIGTERM") and os.name != "nt" else ()
    ):
        try:
            loop.add_signal_handler(sig, router.stop)
        except NotImplementedError:
            pass

    try:
        await router.run()
    finally:
        await bus.close()
        await state.close()


def cli() -> None:
    parser = argparse.ArgumentParser(description="Synapse Router (L1 + L2)")
    parser.add_argument("--session", required=True, help="Session ID to consume")
    parser.add_argument(
        "--redis-url",
        default=os.getenv("SYNAPSE_REDIS_URL", "redis://localhost:6379/0"),
    )
    parser.add_argument(
        "--postgres-dsn",
        default=os.getenv(
            "SYNAPSE_POSTGRES_DSN",
            "postgresql://synapse:synapse_dev@localhost:5432/synapse",
        ),
    )
    parser.add_argument("--consumer", default="r1")
    args = parser.parse_args()
    asyncio.run(main(args.session, args.redis_url, args.postgres_dsn, args.consumer))


if __name__ == "__main__":
    cli()
