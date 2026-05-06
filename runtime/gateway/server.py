"""Synapse Observability Gateway.

A FastAPI service that:
- Subscribes to a session's Redis Stream of envelopes
- Streams those envelopes to browser clients via WebSocket
- Exposes REST endpoints for current state (agents, intentions, beliefs)

The browser UI is a Next.js app that consumes this WebSocket. Together they
form the live "war-room" view of a Synapse session.

Run:
    uvicorn runtime.gateway.server:app --port 8000 --reload
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from synapse.bus import Bus, session_stream
from synapse.state import StateGraph

logger = logging.getLogger("synapse.gateway")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


# ---------------------------------------------------------------------------
# State (single global gateway, multiple sessions multiplexed)
# ---------------------------------------------------------------------------
class GatewayState:
    def __init__(self) -> None:
        self.bus: Optional[Bus] = None
        self.state: Optional[StateGraph] = None
        # session_id -> set of WebSocket connections
        self.subscribers: dict[str, set[WebSocket]] = {}
        # session_id -> consumer task
        self.tail_tasks: dict[str, asyncio.Task] = {}

    async def connect(self) -> None:
        redis_url = os.getenv("SYNAPSE_REDIS_URL", "redis://localhost:6379/0")
        pg_dsn = os.getenv(
            "SYNAPSE_POSTGRES_DSN",
            "postgresql://synapse:synapse_dev@localhost:5432/synapse",
        )
        self.bus = Bus(redis_url)
        self.state = StateGraph(pg_dsn)
        await self.bus.connect()
        await self.state.connect()
        logger.info("Gateway connected to Redis + Postgres")

    async def disconnect(self) -> None:
        for t in list(self.tail_tasks.values()):
            t.cancel()
        if self.bus:
            await self.bus.close()
        if self.state:
            await self.state.close()


_gw = GatewayState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _gw.connect()
    try:
        yield
    finally:
        await _gw.disconnect()


app = FastAPI(title="Synapse Observability Gateway", version="0.1.0", lifespan=lifespan)

# CORS — open in dev so the Next.js dev server (port 3000) can hit us on 8000
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "service": "synapse-gateway"}


@app.get("/sessions")
async def list_sessions() -> dict[str, Any]:
    """List session_ids that have any agents registered."""
    assert _gw.state
    async with _gw.state.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT session_id, COUNT(*) AS agent_count, "
            "MAX(last_heartbeat) AS last_seen "
            "FROM agents GROUP BY session_id ORDER BY last_seen DESC LIMIT 50"
        )
    return {
        "sessions": [
            {
                "session_id": r["session_id"],
                "agent_count": r["agent_count"],
                "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
            }
            for r in rows
        ]
    }


@app.get("/sessions/{session_id}/agents")
async def get_agents(session_id: str) -> dict[str, Any]:
    assert _gw.state
    async with _gw.state.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, status, capabilities, subscribes, scopes_owned,
                      last_heartbeat, created_at
               FROM agents WHERE session_id = $1
               ORDER BY created_at""",
            session_id,
        )
    return {
        "agents": [
            {
                "id": r["id"],
                "status": r["status"],
                "capabilities": _parse_jsonb(r["capabilities"]),
                "subscribes": list(r["subscribes"]),
                "scopes_owned": list(r["scopes_owned"]),
                "last_heartbeat": r["last_heartbeat"].isoformat() if r["last_heartbeat"] else None,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]
    }


@app.get("/sessions/{session_id}/intentions")
async def get_intentions(session_id: str, status: Optional[str] = None) -> dict[str, Any]:
    assert _gw.state
    sql = """SELECT id, agent_id, scope, action, expected_outcome,
                    blocking, status, created_at, resolved_at
             FROM intentions WHERE session_id = $1"""
    args: list[Any] = [session_id]
    if status:
        sql += " AND status = $2"
        args.append(status)
    sql += " ORDER BY created_at DESC LIMIT 200"
    async with _gw.state.pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
    return {
        "intentions": [
            {
                "id": r["id"],
                "agent_id": r["agent_id"],
                "scope": list(r["scope"]),
                "action": _parse_jsonb(r["action"]),
                "expected_outcome": r["expected_outcome"],
                "blocking": r["blocking"],
                "status": r["status"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "resolved_at": r["resolved_at"].isoformat() if r["resolved_at"] else None,
            }
            for r in rows
        ]
    }


@app.get("/sessions/{session_id}/beliefs")
async def get_beliefs(session_id: str) -> dict[str, Any]:
    assert _gw.state
    async with _gw.state.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT agent_id, key, value, confidence, source, updated_at
               FROM beliefs WHERE session_id = $1
               ORDER BY key, updated_at DESC""",
            session_id,
        )
    return {
        "beliefs": [
            {
                "agent_id": r["agent_id"],
                "key": r["key"],
                "value": _parse_jsonb(r["value"]),
                "confidence": float(r["confidence"]),
                "source": r["source"],
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
            for r in rows
        ]
    }


@app.get("/sessions/{session_id}/events")
async def get_recent_events(session_id: str, limit: int = 100) -> dict[str, Any]:
    """Replay the most recent N envelopes from the session stream."""
    assert _gw.bus
    stream = session_stream(session_id)
    # XREVRANGE gives newest first
    raw = await _gw.bus.redis.xrevrange(stream, count=limit)
    out = []
    for entry_id, fields in raw:
        try:
            env = json.loads(fields["e"])
            out.append({"entry_id": entry_id, "envelope": env})
        except Exception:
            continue
    out.reverse()  # chronological
    return {"events": out}


# ---------------------------------------------------------------------------
# WebSocket: /ws/sessions/{session_id}
# ---------------------------------------------------------------------------
@app.websocket("/ws/sessions/{session_id}")
async def session_websocket(ws: WebSocket, session_id: str) -> None:
    await ws.accept()
    _gw.subscribers.setdefault(session_id, set()).add(ws)
    logger.info("WS connect: session=%s subscribers=%d",
                session_id, len(_gw.subscribers[session_id]))

    # Ensure the tail task is running for this session
    if session_id not in _gw.tail_tasks:
        _gw.tail_tasks[session_id] = asyncio.create_task(
            _tail_session(session_id)
        )

    try:
        # Send initial snapshot (agents + active intentions + beliefs)
        await _send_snapshot(ws, session_id)
        # Now just block on disconnect (tail_session pushes new events)
        while True:
            msg = await ws.receive_text()
            # Echo a hello-back for ping/keepalive
            if msg == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        _gw.subscribers.get(session_id, set()).discard(ws)
        logger.info("WS disconnect: session=%s remaining=%d",
                    session_id, len(_gw.subscribers.get(session_id, set())))


async def _send_snapshot(ws: WebSocket, session_id: str) -> None:
    """On connect, send agents/intentions/beliefs so the UI starts populated."""
    agents = await get_agents(session_id)
    intentions = await get_intentions(session_id)
    beliefs = await get_beliefs(session_id)
    events = await get_recent_events(session_id, limit=50)
    await ws.send_text(json.dumps({
        "type": "snapshot",
        "agents": agents["agents"],
        "intentions": intentions["intentions"],
        "beliefs": beliefs["beliefs"],
        "events": events["events"],
    }))


async def _tail_session(session_id: str) -> None:
    """Consume the session stream and broadcast each new envelope to all WS subscribers."""
    assert _gw.bus
    stream = session_stream(session_id)
    last_id = "$"
    logger.info("Tailing %s for WS broadcast", stream)
    while True:
        try:
            resp = await _gw.bus.redis.xread(
                streams={stream: last_id}, count=64, block=2000
            )
        except Exception as e:
            logger.warning("Gateway tail read error on %s: %s", stream, e)
            await asyncio.sleep(1)
            continue
        if not resp:
            # No new data in the block window. Cleanup if no subscribers.
            if not _gw.subscribers.get(session_id):
                logger.info("No subscribers for %s; stopping tail", session_id)
                _gw.tail_tasks.pop(session_id, None)
                return
            continue
        for _, entries in resp:
            for entry_id, fields in entries:
                last_id = entry_id
                try:
                    env = json.loads(fields["e"])
                except Exception:
                    continue
                payload = json.dumps({
                    "type": "event",
                    "entry_id": entry_id,
                    "envelope": env,
                })
                # Broadcast to all subscribers of this session
                dead: list[WebSocket] = []
                for sub in list(_gw.subscribers.get(session_id, set())):
                    try:
                        await sub.send_text(payload)
                    except Exception:
                        dead.append(sub)
                for d in dead:
                    _gw.subscribers.get(session_id, set()).discard(d)


# ---------------------------------------------------------------------------
def _parse_jsonb(v: Any) -> Any:
    """Postgres asyncpg returns JSONB as either str or already-parsed Python.
    Handle both."""
    if isinstance(v, (dict, list)):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return v
    return v
