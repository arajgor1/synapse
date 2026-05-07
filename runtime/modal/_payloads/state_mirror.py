"""Stream → state-graph mirror + Router for non-Python clients.

The TypeScript SDK only publishes envelopes to the Redis bus (it doesn't
have an asyncpg-equivalent). For multi-agent conflict detection to fire,
intentions must live in Postgres (the L2 router queries them via SQL).

This sidecar fixes the gap: it consumes the session stream and:
  - On INTENTION: ensure the agent row exists, insert the intention.
  - On RESOLUTION: mark the parent intention resolved.
  - Then runs the existing Synapse Router (L1 + L2) on the same stream.

Used by the Paperclip and OpenClaw real product-dev tests, which drive
the integrations from Node. The Hermes test doesn't need this — its
integration uses the Python SDK directly.

Run: python state_mirror.py <session_id>
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, "/opt/synapse-sdk")
sys.path.insert(0, "/opt")

logger = logging.getLogger("synapse.state_mirror")


REDIS_URL = os.environ.get(
    "SYNAPSE_REDIS_URL", "redis://localhost:6379/0"
)
PG_DSN = os.environ.get(
    "SYNAPSE_POSTGRES_DSN",
    "postgresql://synapse:synapse_dev@localhost:5432/synapse",
)


async def mirror_loop(session_id: str, state, redis, stop_evt: asyncio.Event):
    """Consume the session stream and mirror INTENTION/RESOLUTION to PG."""
    stream = f"synapse:session:{session_id}:events"
    last_id = "0"
    seen_intentions: set[str] = set()
    seen_agents: set[str] = set()
    while not stop_evt.is_set():
        entries = await redis.xread({stream: last_id}, block=200, count=50)
        if not entries:
            continue
        for _stream, batch in entries:
            for entry_id, fields in batch:
                last_id = entry_id
                try:
                    env = json.loads(fields["e"])
                except Exception:
                    continue
                t = env.get("type")
                agent_id = env.get("agent_id")
                if t == "INTENTION":
                    if agent_id and agent_id not in seen_agents:
                        # Ensure agent row (idempotent)
                        await state.pool.execute(
                            """
                            INSERT INTO agents (
                                id, session_id, tenant_id, status, capabilities,
                                subscribes, scopes_owned
                            ) VALUES ($1,$2,$3,'active',$4::jsonb,$5,$6)
                            ON CONFLICT (id) DO UPDATE SET status='active'
                            """,
                            agent_id, session_id, env.get("tenant_id"),
                            "{}", [], [],
                        )
                        seen_agents.add(agent_id)
                    if env["msg_id"] not in seen_intentions:
                        payload = env.get("payload") or {}
                        await state.pool.execute(
                            """
                            INSERT INTO intentions (
                                id, agent_id, session_id, tenant_id, scope,
                                action, expected_outcome, blocking, status
                            ) VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,'active')
                            ON CONFLICT (id) DO NOTHING
                            """,
                            env["msg_id"], agent_id, session_id,
                            env.get("tenant_id"),
                            list(payload.get("scope", [])),
                            json.dumps(payload.get("action", {})),
                            payload.get("expected_outcome", ""),
                            bool(payload.get("blocking", False)),
                        )
                        seen_intentions.add(env["msg_id"])
                elif t == "RESOLUTION":
                    payload = env.get("payload") or {}
                    int_id = payload.get("intention_id")
                    if int_id:
                        await state.pool.execute(
                            "UPDATE intentions SET status='resolved', "
                            "resolved_at=now() WHERE id=$1 AND status='active'",
                            int_id,
                        )


async def main(session_id: str) -> None:
    logging.basicConfig(
        level=os.getenv("SYNAPSE_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    from synapse.bus import Bus
    from synapse.state import StateGraph
    from runtime.router.worker import Router

    bus = Bus(REDIS_URL)
    state = StateGraph(PG_DSN)
    await bus.connect()
    await state.connect()

    stop = asyncio.Event()
    mirror_task = asyncio.create_task(
        mirror_loop(session_id, state, bus.redis, stop)
    )

    router = Router(bus, state, session_id, consumer="state_mirror_router")
    router_task = asyncio.create_task(router.run())

    # Run until killed (parent process will SIGTERM)
    try:
        await asyncio.gather(mirror_task, router_task)
    except asyncio.CancelledError:
        pass
    finally:
        stop.set()
        router.stop()
        await bus.close()
        await state.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: state_mirror.py <session_id>", file=sys.stderr)
        sys.exit(2)
    try:
        asyncio.run(main(sys.argv[1]))
    except KeyboardInterrupt:
        pass
