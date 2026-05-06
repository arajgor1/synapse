"""Postgres state graph client.

Provides agent registration, intention claim/release, and the load-bearing
scope-overlap query used by L2 conflict detection.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import asyncpg

from synapse.messages import AgentRegistration, Intention

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scope matching helpers — mirrors spec/conflict-semantics.md
# ---------------------------------------------------------------------------
_MOD_RE = re.compile(r":(r|w|rw)$")


def parse_scope(scope: str) -> tuple[str, str]:
    """Split 'auth.middleware:w' into ('auth.middleware', 'w'). Default mode 'rw'."""
    m = _MOD_RE.search(scope)
    if not m:
        return scope, "rw"
    base = scope[: m.start()]
    return base, m.group(1)


def has_write(mode: str) -> bool:
    return "w" in mode


def patterns_intersect(a: str, b: str) -> bool:
    """Pattern intersection per spec/conflict-semantics.md.

    - Exact == exact: equal.
    - Single-segment * matches one segment.
    - Multi-segment ** matches one or more segments.
    """
    a_parts = a.split(".")
    b_parts = b.split(".")
    return _intersect_parts(a_parts, b_parts)


def _intersect_parts(a: list[str], b: list[str]) -> bool:
    # Multi-segment wildcard — recursive
    if a and a[0] == "**":
        # a's ** can match zero or more segments
        if not a[1:]:
            return True
        return any(_intersect_parts(a[1:], b[i:]) for i in range(len(b) + 1))
    if b and b[0] == "**":
        if not b[1:]:
            return True
        return any(_intersect_parts(a[i:], b[1:]) for i in range(len(a) + 1))
    if not a or not b:
        return not a and not b
    head_a, head_b = a[0], b[0]
    if head_a == "*" or head_b == "*" or head_a == head_b:
        return _intersect_parts(a[1:], b[1:])
    return False


def conflicts(a_scope: str, b_scope: str) -> bool:
    """Two scopes conflict if patterns intersect AND at least one writes."""
    a_base, a_mode = parse_scope(a_scope)
    b_base, b_mode = parse_scope(b_scope)
    if not patterns_intersect(a_base, b_base):
        return False
    return has_write(a_mode) or has_write(b_mode)


def find_overlapping_scopes(
    new_scopes: list[str], existing_scopes: list[str]
) -> list[str]:
    """Return the subset of new_scopes that conflict with any existing_scope."""
    overlapping: set[str] = set()
    for ns in new_scopes:
        for es in existing_scopes:
            if conflicts(ns, es):
                overlapping.add(ns)
                break
    return sorted(overlapping)


# ---------------------------------------------------------------------------
# State client
# ---------------------------------------------------------------------------
class StateGraph:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=8)
        logger.info("StateGraph connected")

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("StateGraph not connected. Call connect() first.")
        return self._pool

    async def register_agent(self, reg: AgentRegistration) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO agents (id, session_id, tenant_id, status, capabilities,
                                    subscribes, scopes_owned, last_heartbeat, created_at)
                VALUES ($1, $2, $3, 'active', $4::jsonb, $5, $6, now(), now())
                ON CONFLICT (id) DO UPDATE
                  SET session_id = EXCLUDED.session_id,
                      tenant_id = EXCLUDED.tenant_id,
                      status = 'active',
                      capabilities = EXCLUDED.capabilities,
                      subscribes = EXCLUDED.subscribes,
                      scopes_owned = EXCLUDED.scopes_owned,
                      last_heartbeat = now()
                """,
                reg.agent_id,
                reg.session_id,
                reg.tenant_id,
                json.dumps(reg.capabilities.model_dump()),
                reg.subscribes,
                reg.scopes_owned,
            )
        logger.info("Registered agent %s in session %s", reg.agent_id, reg.session_id)

    async def heartbeat(self, agent_id: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE agents SET last_heartbeat = now() WHERE id = $1", agent_id
            )

    async def insert_intention(
        self,
        *,
        intention_id: str,
        agent_id: str,
        session_id: str,
        tenant_id: Optional[str],
        intention: Intention,
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO intentions (id, agent_id, session_id, tenant_id,
                                        scope, action, expected_outcome, blocking,
                                        status, created_at)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, 'active', now())
                ON CONFLICT (id) DO NOTHING
                """,
                intention_id,
                agent_id,
                session_id,
                tenant_id,
                intention.scope,
                json.dumps(intention.action),
                intention.expected_outcome,
                intention.blocking,
            )

    async def resolve_intention(
        self, intention_id: str, status: str = "resolved"
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE intentions SET status = $2, resolved_at = now()
                WHERE id = $1 AND status = 'active'
                """,
                intention_id,
                status,
            )

    async def find_conflicts(
        self,
        *,
        new_intention_id: str,
        agent_id: str,
        session_id: str,
        scope: list[str],
    ) -> list[dict[str, Any]]:
        """Find active intentions in the same session, by other agents, with overlapping scope.

        Two-step approach:
        1) Coarse SQL filter via array overlap (GIN-indexed). Catches exact-match
           and same-prefix scopes.
        2) Fine refinement in Python via the conflict-semantics matcher
           (handles wildcards and read/write modifiers).
        """
        # Strip modifiers for the coarse SQL match — we check modifiers in step 2.
        bases = [parse_scope(s)[0] for s in scope]

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, agent_id, scope, EXTRACT(EPOCH FROM created_at)*1000 AS started_ms
                FROM intentions
                WHERE session_id = $1
                  AND status = 'active'
                  AND agent_id != $2
                  AND id != $3
                """,
                session_id,
                agent_id,
                new_intention_id,
            )

        conflicts_out: list[dict[str, Any]] = []
        for r in rows:
            existing_scopes: list[str] = list(r["scope"])
            overlap = find_overlapping_scopes(scope, existing_scopes)
            if not overlap:
                # Try the bases too — for cases where SQL would have matched but
                # the modifier check excluded it. (Belt-and-suspenders.)
                continue
            conflicts_out.append(
                {
                    "intention_id": r["id"],
                    "agent_id": r["agent_id"],
                    "scope": existing_scopes,
                    "started_at_ms": int(r["started_ms"]),
                    "overlapping_scopes": overlap,
                }
            )
        return conflicts_out
