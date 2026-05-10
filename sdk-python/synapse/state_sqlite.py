"""SQLite implementation of the StateGraph protocol for zero-infra mode.

Mirrors the surface of ``synapse.state.StateGraph`` (Postgres) so the
Agent and intend() flows work unchanged. Uses ``aiosqlite`` if available;
falls back to wrapping the stdlib ``sqlite3`` module in ``asyncio.to_thread``
otherwise. The fallback is fine for single-process zero-infra mode — we
don't need real async I/O when there's only one writer.

Schema parity
-------------
Same logical schema as Postgres (agents, intentions) with adjustments:
  * ``jsonb`` -> ``TEXT`` (we json.dumps/loads at the boundary).
  * ``text[]`` -> ``TEXT`` storing JSON-encoded array. We expand for
    overlap matching in Python (same fine-grained matcher as Postgres).
  * ``timestamptz`` -> ``REAL`` (epoch milliseconds) for portable sort
    and arithmetic without timezone gymnastics.
  * No GIN index on scope; we read the full active+recent set into Python
    and use ``synapse.state.find_overlapping_scopes``. Volume is single-
    process so this is well within the budget.

File location
-------------
Default: ``~/.synapse/state.db``. Can be overridden via the ``dsn`` arg
which accepts either a path or a ``sqlite:///`` URL. The directory is
created on first connect.

Concurrency
-----------
Single-process means one writer; we still enable WAL mode so concurrent
async readers don't block writes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from synapse.messages import AgentRegistration, Intention
from synapse.state import find_overlapping_scopes, parse_scope

logger = logging.getLogger(__name__)


def _resolve_path(dsn: Optional[str]) -> Path:
    if not dsn:
        # Default — mirrors "config home" conventions on Linux + a sensible
        # equivalent on Windows.
        home = Path.home()
        return home / ".synapse" / "state.db"
    if dsn.startswith("sqlite:///"):
        return Path(dsn[len("sqlite:///"):])
    if dsn.startswith("sqlite://"):
        # sqlite:// (two slashes) is a relative path on some libraries
        return Path(dsn[len("sqlite://"):])
    return Path(dsn)


_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS agents (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        tenant_id TEXT,
        status TEXT NOT NULL CHECK (status IN ('active','idle','crashed')),
        capabilities TEXT NOT NULL,
        subscribes TEXT NOT NULL DEFAULT '[]',
        scopes_owned TEXT NOT NULL DEFAULT '[]',
        last_heartbeat REAL NOT NULL,
        created_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS intentions (
        id TEXT PRIMARY KEY,
        agent_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        tenant_id TEXT,
        scope TEXT NOT NULL,
        action TEXT NOT NULL,
        expected_outcome TEXT NOT NULL,
        blocking INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL CHECK (status IN ('pending','active','resolved','pivoted')),
        created_at REAL NOT NULL,
        resolved_at REAL
    )
    """,
    "CREATE INDEX IF NOT EXISTS intentions_session_idx ON intentions(session_id, status)",
    "CREATE INDEX IF NOT EXISTS intentions_agent_idx   ON intentions(agent_id)",
    """
    CREATE TABLE IF NOT EXISTS beliefs (
        agent_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        tenant_id TEXT,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        confidence REAL NOT NULL,
        source TEXT NOT NULL,
        evidence TEXT,
        updated_at REAL NOT NULL,
        PRIMARY KEY (agent_id, key)
    )
    """,
]


class SqliteStateGraph:
    """Drop-in replacement for ``synapse.state.StateGraph`` (Postgres).

    Async surface preserved; under the hood we run sqlite3 calls inside
    ``asyncio.to_thread`` to keep the event loop unblocked.
    """

    def __init__(self, dsn: Optional[str] = None) -> None:
        self._path = _resolve_path(dsn)
        self._conn: Optional[sqlite3.Connection] = None
        # Single-writer lock — sqlite3 is internally serialised but we
        # want to surface backpressure rather than busy-wait the kernel.
        self._lock = asyncio.Lock()

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------
    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False because we drive sqlite3 from the asyncio
        # default executor which uses different threads. The asyncio.Lock
        # serialises us so it's safe.
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=OFF")  # we don't use FKs here
        for stmt in _SCHEMA:
            self._conn.execute(stmt)
        self._conn.commit()
        logger.info("SqliteStateGraph connected: %s (zero-infra mode)", self._path)

    async def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    # -----------------------------------------------------------------
    # Internal exec helpers
    # -----------------------------------------------------------------
    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("SqliteStateGraph not connected. Call connect() first.")
        return self._conn

    async def _execute(self, sql: str, params: tuple = ()) -> None:
        async with self._lock:
            def _do() -> None:
                conn = self._require_conn()
                conn.execute(sql, params)
                conn.commit()
            await asyncio.to_thread(_do)

    async def _fetchall(self, sql: str, params: tuple = ()) -> list[tuple]:
        async with self._lock:
            def _do() -> list[tuple]:
                conn = self._require_conn()
                cur = conn.execute(sql, params)
                return cur.fetchall()
            return await asyncio.to_thread(_do)

    # -----------------------------------------------------------------
    # Agent registry
    # -----------------------------------------------------------------
    async def register_agent(self, reg: AgentRegistration) -> None:
        now = time.time()
        await self._execute(
            """
            INSERT INTO agents (id, session_id, tenant_id, status, capabilities,
                                subscribes, scopes_owned, last_heartbeat, created_at)
            VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                session_id     = excluded.session_id,
                tenant_id      = excluded.tenant_id,
                status         = 'active',
                capabilities   = excluded.capabilities,
                subscribes     = excluded.subscribes,
                scopes_owned   = excluded.scopes_owned,
                last_heartbeat = excluded.last_heartbeat
            """,
            (
                reg.agent_id,
                reg.session_id,
                reg.tenant_id,
                json.dumps(reg.capabilities.model_dump()),
                json.dumps(reg.subscribes),
                json.dumps(reg.scopes_owned),
                now,
                now,
            ),
        )

    async def heartbeat(self, agent_id: str) -> None:
        await self._execute(
            "UPDATE agents SET last_heartbeat = ? WHERE id = ?",
            (time.time(), agent_id),
        )

    # -----------------------------------------------------------------
    # Intentions
    # -----------------------------------------------------------------
    async def insert_intention(
        self,
        *,
        intention_id: str,
        agent_id: str,
        session_id: str,
        tenant_id: Optional[str],
        intention: Intention,
    ) -> None:
        await self._execute(
            """
            INSERT OR IGNORE INTO intentions
                (id, agent_id, session_id, tenant_id, scope, action,
                 expected_outcome, blocking, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
            """,
            (
                intention_id,
                agent_id,
                session_id,
                tenant_id,
                json.dumps(intention.scope),
                json.dumps(intention.action),
                intention.expected_outcome,
                1 if intention.blocking else 0,
                time.time(),
            ),
        )

    async def resolve_intention(
        self, intention_id: str, status: str = "resolved"
    ) -> None:
        await self._execute(
            """
            UPDATE intentions SET status = ?, resolved_at = ?
            WHERE id = ? AND status = 'active'
            """,
            (status, time.time(), intention_id),
        )

    # -----------------------------------------------------------------
    # Intention status (used by queue_behind / retry_with_backoff policies)
    # -----------------------------------------------------------------
    async def intentions_active_in(
        self, intention_ids: list[str], session_id: str
    ) -> set[str]:
        if not intention_ids:
            return set()
        placeholders = ",".join("?" for _ in intention_ids)
        rows = await self._fetchall(
            f"SELECT id FROM intentions "
            f"WHERE session_id = ? AND status = 'active' "
            f"AND id IN ({placeholders})",
            (session_id, *intention_ids),
        )
        return {r[0] for r in rows}

    # -----------------------------------------------------------------
    # Beliefs (backend-agnostic API mirroring synapse.state.StateGraph)
    # -----------------------------------------------------------------
    async def belief_upsert(
        self,
        *,
        agent_id: str,
        session_id: str,
        tenant_id: Optional[str],
        key: str,
        value: Any,
        confidence: float,
        source: str,
        evidence: Optional[str],
    ) -> None:
        await self._execute(
            """
            INSERT INTO beliefs (agent_id, session_id, tenant_id, key, value,
                                 confidence, source, evidence, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_id, key) DO UPDATE SET
                value      = excluded.value,
                confidence = excluded.confidence,
                source     = excluded.source,
                evidence   = excluded.evidence,
                updated_at = excluded.updated_at,
                session_id = excluded.session_id
            """,
            (
                agent_id, session_id, tenant_id, key, json.dumps(value),
                confidence, source, evidence, time.time(),
            ),
        )

    async def beliefs_for_session(self, session_id: str) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            "SELECT agent_id, key, value, confidence, source "
            "FROM beliefs WHERE session_id = ?",
            (session_id,),
        )
        return [
            {
                "agent_id": agent_id,
                "key": key,
                "value": json.loads(value) if isinstance(value, str) else value,
                "confidence": confidence,
                "source": source,
            }
            for (agent_id, key, value, confidence, source) in rows
        ]

    async def beliefs_for_key(
        self, session_id: str, key: str
    ) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            "SELECT agent_id, key, value, confidence, source "
            "FROM beliefs WHERE session_id = ? AND key = ?",
            (session_id, key),
        )
        return [
            {
                "agent_id": agent_id,
                "key": k,
                "value": json.loads(v) if isinstance(v, str) else v,
                "confidence": conf,
                "source": src,
            }
            for (agent_id, k, v, conf, src) in rows
        ]

    async def find_conflicts(
        self,
        *,
        new_intention_id: str,
        agent_id: str,
        session_id: str,
        scope: list[str],
        resolved_lookback_ms: int = 60_000,
    ) -> list[dict[str, Any]]:
        """Same semantics as the Postgres find_conflicts.

        We pull the (active OR recently-resolved) intentions for this
        session in one query, then do the fine scope-overlap match in
        Python via the shared ``find_overlapping_scopes`` helper —
        identical to the Postgres path's step-2 refinement.
        """
        cutoff_s = time.time() - (resolved_lookback_ms / 1000.0)
        rows = await self._fetchall(
            """
            SELECT id, agent_id, scope, status,
                   created_at, resolved_at
            FROM intentions
            WHERE session_id = ?
              AND agent_id != ?
              AND id != ?
              AND (status = 'active'
                   OR (status = 'resolved' AND resolved_at >= ?))
            """,
            (session_id, agent_id, new_intention_id, cutoff_s),
        )
        out: list[dict[str, Any]] = []
        for (other_id, other_agent, scope_json, status, created_at, resolved_at) in rows:
            try:
                existing_scopes = json.loads(scope_json)
            except Exception:
                continue
            overlap = find_overlapping_scopes(scope, existing_scopes)
            if not overlap:
                continue
            kind = "active" if status == "active" else "recent_resolution"
            out.append({
                "intention_id": other_id,
                "agent_id": other_agent,
                "scope": existing_scopes,
                "started_at_ms": int((created_at or 0) * 1000),
                "overlapping_scopes": overlap,
                "kind": kind,
                "resolved_at_ms": (
                    int(resolved_at * 1000) if resolved_at else None
                ),
            })
        return out
