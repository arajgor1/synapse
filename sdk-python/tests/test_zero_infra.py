"""End-to-end test for zero-infra mode.

This is the test that proves Synapse provides real coordination value
to a fresh user with no Redis, no Postgres, no env vars set — the
single biggest onboarding cliff identified in the user-perspective gap
audit.

What we assert
--------------
1. Two ``asyncio.gather``'d coroutines, each in its own ``with_agent``
   block, claim overlapping write scopes via ``synapse.intend()``.
2. Synapse's in-process L2 router detects the overlap and pushes a
   CONFLICT envelope back to at least one agent's inbox during the gate
   window.
3. The gate window observes the CONFLICT and ``IntentionHandle.has_conflicts``
   reports True for the second-arriving agent (or both, depending on
   timing — we assert at least one).
4. Both INTENTIONs get persisted to the SQLite state graph at the
   default ``~/.synapse/state.db`` path (we point it at a tmp path).
5. Both INTENTIONs land with distinct agent IDs, proving the v0.2.2a2
   ContextVar attribution fix carries through the zero-infra path too.

What we do NOT assert
---------------------
* Multi-process coordination — explicitly out of scope for in-memory bus.
* Persistence across restarts — sqlite covers it but each test starts
  with a fresh tmp file so we don't depend on that.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path

import pytest

import synapse
from synapse.intend import shutdown as synapse_shutdown


@pytest.fixture(autouse=True)
async def _isolate_runtime(tmp_path, monkeypatch):
    """Fresh runtime + isolated SQLite path per test. Ensures we test
    real zero-infra startup each time, not residual state."""
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    monkeypatch.delenv("SYNAPSE_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("SYNAPSE_OFFLINE", raising=False)
    monkeypatch.setenv("SYNAPSE_SQLITE_PATH", str(tmp_path / "state.db"))
    # Force a fresh runtime by tearing down any prior test's state.
    await synapse_shutdown()
    yield
    await synapse_shutdown()


@pytest.mark.asyncio
async def test_zero_infra_emits_intentions_and_persists_to_sqlite(tmp_path):
    """Bare minimum: with no infra env vars set, intend() still emits
    INTENTIONs and they land in the SQLite state file."""
    sqlite_path = Path(os.environ["SYNAPSE_SQLITE_PATH"])
    session = "zero_infra_test_session"

    async def call(name: str, content: str):
        with synapse.with_agent(name):
            async with synapse.intend(
                scope=[f"repo.fs.app/models.py:w"],
                agent=name,
                session=session,
                expected_outcome="zero-infra coordination",
                blocking=False,  # don't gate — we just want emission proof
            ) as i:
                i.set_state_diff({"output_preview": content})

    await asyncio.gather(call("alice", "alice writes"), call("bob", "bob writes"))

    # Give the in-process router a moment to drain and the resolution
    # writes to land. asyncio.sleep(0.2) is generous.
    await asyncio.sleep(0.2)

    # The SQLite file MUST exist — proves zero-infra picked the SQLite
    # backend even with no SYNAPSE_POSTGRES_DSN set.
    assert sqlite_path.exists(), (
        f"SQLite state file not created at {sqlite_path}. "
        "Zero-infra mode probably didn't engage."
    )

    # Two distinct INTENTIONs must be persisted.
    conn = sqlite3.connect(sqlite_path)
    rows = conn.execute(
        "SELECT agent_id, scope, status FROM intentions WHERE session_id = ?",
        (session,),
    ).fetchall()
    conn.close()

    agent_ids = {r[0] for r in rows}
    assert len(rows) >= 2, f"Expected ≥2 intentions, got {len(rows)}: {rows}"
    assert agent_ids == {"alice", "bob"}, (
        f"Attribution collapsed under gather (env-var race regression?): "
        f"got {agent_ids}, expected {{'alice','bob'}}"
    )


@pytest.mark.asyncio
async def test_zero_infra_router_detects_conflict_in_gate_window():
    """The in-process router must detect a scope overlap between two
    concurrent intentions and push a CONFLICT into the second arriver's
    inbox during its gate window."""
    session = "zero_infra_conflict_session"
    scope = ["repo.fs.shared/db.py:w"]

    handles: dict[str, synapse.IntentionHandle] = {}

    async def slow_alice():
        with synapse.with_agent("alice"):
            async with synapse.intend(
                scope=scope, agent="alice", session=session,
                expected_outcome="alice slow write",
                blocking=True,
                gate_ms=300,  # generous so bob can arrive while alice is active
            ) as i:
                handles["alice"] = i
                # Stay active so bob's intention overlaps with active alice.
                await asyncio.sleep(0.5)

    async def fast_bob():
        # Slight delay so alice's INTENTION + register lands first.
        await asyncio.sleep(0.05)
        with synapse.with_agent("bob"):
            async with synapse.intend(
                scope=scope, agent="bob", session=session,
                expected_outcome="bob fast write",
                blocking=True,
                gate_ms=300,
            ) as i:
                handles["bob"] = i

    await asyncio.gather(slow_alice(), fast_bob())

    # At LEAST one of the two should have observed the conflict during
    # its gate window. (Alice may not — her intention came first; bob
    # arrived while alice was active so bob is the one who must see it.)
    bob_handle = handles.get("bob")
    assert bob_handle is not None, "bob never ran — test setup broken"
    assert bob_handle.has_conflicts, (
        "Zero-infra in-process router did not deliver CONFLICT to bob "
        "during gate window. Either the router didn't start, didn't "
        "detect the overlap, or didn't publish to bob's inbox in time."
    )
    # The conflict should reference alice as the conflicting agent.
    other_agents = {
        ci.agent_id
        for c in bob_handle.conflicts
        for ci in c.conflicting_intentions
    }
    assert "alice" in other_agents, (
        f"CONFLICT didn't surface alice as the conflicting agent; saw {other_agents}"
    )


@pytest.mark.asyncio
async def test_zero_infra_belief_divergence_without_infra():
    """Beliefs + live divergence detection must work in zero-infra mode.

    Two agents emit conflicting beliefs about the same key. The second
    agent's emit should surface a divergence result via the SQLite-backed
    state graph — proving the belief subsystem is backend-agnostic, not
    Postgres-only.
    """
    session = "zero_infra_belief_session"

    # Agent alice claims revenue formula = qty*price
    div_a = await synapse.emit_belief(
        agent="alice", session=session,
        key="revenue_formula", value="qty * price",
        confidence=0.95, source="observed",
    )
    # Single agent, no divergence yet
    assert div_a is None

    # Agent bob claims a different formula — divergence must fire
    div_b = await synapse.emit_belief(
        agent="bob", session=session,
        key="revenue_formula", value="qty * price - discount",
        confidence=0.9, source="observed",
    )
    assert div_b is not None, (
        "Belief divergence not detected in zero-infra mode. "
        "Likely the belief subsystem still relies on Postgres-only state.pool."
    )
    assert div_b.key == "revenue_formula"
    assert {a for a in div_b.agents_involved} >= {"alice", "bob"}
    assert len(div_b.distinct_values) >= 2


@pytest.mark.asyncio
async def test_zero_infra_no_redis_no_postgres_no_env(monkeypatch):
    """Sanity: confirm we genuinely engaged zero-infra mode and not the
    live Redis/Postgres path through some env-var leak."""
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    monkeypatch.delenv("SYNAPSE_POSTGRES_DSN", raising=False)
    # First call into intend() triggers _get_or_init_runtime
    async with synapse.intend(
        scope=["test.scope:w"],
        agent="probe", session="probe-sess",
        blocking=False,
    ):
        pass
    from synapse.intend import _runtime
    assert _runtime.get("mode") == "zero-infra", (
        f"Expected zero-infra mode, got {_runtime.get('mode')}. "
        "Probably leaked SYNAPSE_REDIS_URL from a prior test."
    )
    assert _runtime.get("state_backend") == "sqlite"
    # Bus must be the in-memory implementation.
    from synapse.bus_inmemory import InMemoryBus
    assert isinstance(_runtime.get("bus"), InMemoryBus)
