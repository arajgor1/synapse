"""Phase 1 deliverable — two-agent conflict demo.

Demonstrates Synapse's core value end-to-end:

1. Two agents (A and B) register in the same session.
2. Agent A emits an INTENTION claiming scope=['auth.middleware:w'].
3. Agent B emits an INTENTION claiming scope=['auth.middleware:w'].
4. The router (running in-process for the demo) detects the scope overlap.
5. Agent B's pre-execution gate receives a CONFLICT signal within the gate window.
6. Agent B prints the CONFLICT details and pivots — without any human in the loop.

Prerequisites:
- docker compose up -d (Redis + Postgres + initial migrations)
- pip install -e sdk-python (from repo root)

Run:
    python examples/two_agents_conflict_demo.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid

# Make the repo's sdk-python importable when running from a checkout.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_REPO_ROOT, "sdk-python"))
sys.path.insert(0, _REPO_ROOT)

from synapse import Agent  # noqa: E402
from synapse.adapters import MockAdapter  # noqa: E402
from synapse.bus import Bus  # noqa: E402
from synapse.state import StateGraph  # noqa: E402
from runtime.router.worker import Router  # noqa: E402


REDIS_URL = os.getenv("SYNAPSE_REDIS_URL", "redis://localhost:6379/0")
POSTGRES_DSN = os.getenv(
    "SYNAPSE_POSTGRES_DSN",
    "postgresql://synapse:synapse_dev@localhost:5432/synapse",
)


def _section(title: str) -> None:
    print(f"\n{'=' * 70}\n  {title}\n{'=' * 70}")


async def _wait_for_ready(name: str, connect_fn, retries: int = 60, delay_s: float = 1.0) -> None:
    """Generic wait-for-ready: retries `connect_fn()` until it succeeds or retries exhaust.

    Default 60s total to cover Docker Desktop cold-start (Redis + Postgres both
    take noticeable time on first boot).
    """
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            await connect_fn()
            if attempt > 0:
                print(f"  [{name}] connected after {attempt + 1} attempt(s)")
            return
        except Exception as e:
            last_err = e
            if attempt == 0:
                print(f"  [{name}] not ready yet (waiting up to {retries * delay_s:.0f}s)…")
            await asyncio.sleep(delay_s)
    raise RuntimeError(
        f"{name} not ready after {retries * delay_s:.0f}s. "
        f"Is Docker Desktop running? `docker compose ps` should show both containers healthy. "
        f"Last error: {last_err}"
    )


async def main() -> int:
    logging.basicConfig(
        level=os.getenv("SYNAPSE_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    session_id = f"demo_{uuid.uuid4().hex[:8]}"
    _section(f"Synapse two-agent conflict demo  [session={session_id}]")

    bus = Bus(REDIS_URL)
    state = StateGraph(POSTGRES_DSN)
    await _wait_for_ready("redis", bus.connect)
    await _wait_for_ready("postgres", state.connect)

    backend_a = MockAdapter(scripted_response="Agent A initial work")
    backend_b = MockAdapter(scripted_response="Agent B initial work")

    agent_a = Agent(
        id="agent_a",
        session=session_id,
        backend=backend_a,
        subscribes=["auth.*"],
        scopes_owned=["auth.middleware"],
        bus=bus,
        state=state,
    )
    agent_b = Agent(
        id="agent_b",
        session=session_id,
        backend=backend_b,
        subscribes=["auth.*"],
        scopes_owned=[],
        bus=bus,
        state=state,
    )

    # Start the router in the background.
    router = Router(bus, state, session_id, consumer="demo_router")
    router_task = asyncio.create_task(router.run())

    try:
        async with agent_a.lifecycle(), agent_b.lifecycle():
            _section("Step 1: Agent A claims auth.middleware (write)")
            a_intention_id, a_conflicts = await agent_a.emit_intention(
                action={"tool": "edit_file", "args": {"path": "auth/middleware.py"}},
                scope=["auth.middleware:w"],
                expected_outcome="Refactor middleware to use token-bucket rate limiter",
                blocking=False,
            )
            print(f"  Agent A intention emitted: {a_intention_id}")
            print(f"  Agent A conflicts at gate: {a_conflicts}")
            assert not a_conflicts, "Agent A should be first; no conflicts expected"

            # Give the router a beat to ingest A's intention before B emits.
            await asyncio.sleep(0.1)

            _section("Step 2: Agent B tries to claim the same scope (with gate)")
            b_intention_id, b_conflicts = await agent_b.emit_intention(
                action={"tool": "edit_file", "args": {"path": "auth/middleware.py"}},
                scope=["auth.middleware:w"],
                expected_outcome="Add structured logging to middleware",
                blocking=True,
                gate_ms=500,  # Generous for demo; production default is 50ms
            )
            print(f"  Agent B intention emitted: {b_intention_id}")

            if b_conflicts:
                _section("Step 3: CONFLICT detected — Agent B pivots")
                for c in b_conflicts:
                    print(f"  Kind:               {c.kind}")
                    print(f"  Overlapping scopes: {c.overlapping_scopes}")
                    print(f"  Suggested:          {c.suggested_resolution}")
                    print(f"  Rationale:          {c.rationale}")
                    for ci in c.conflicting_intentions:
                        print(
                            f"  Conflicts with:     {ci.agent_id} "
                            f"(intention={ci.intention_id}) on scope {ci.scope}"
                        )

                _section("Step 4: Agent B narrows scope and retries")
                b2_intention_id, b2_conflicts = await agent_b.emit_intention(
                    action={"tool": "edit_file", "args": {"path": "auth/logging.py"}},
                    scope=["auth.logging:w"],
                    expected_outcome="Add structured logging in a separate module",
                    blocking=True,
                    gate_ms=500,
                )
                print(f"  Agent B retry intention: {b2_intention_id}")
                print(f"  Agent B conflicts on retry: {b2_conflicts}")
                assert not b2_conflicts, "Narrowed scope should not conflict"

                _section("Step 5: Agent A resolves; both finish cleanly")
                await agent_a.emit_resolution(intention_id=a_intention_id)
                await agent_b.emit_resolution(intention_id=b2_intention_id)
                print("  Both intentions resolved.")
                print("\n[demo] Coordination protocol verified end-to-end.")
                return 0
            else:
                print("\n[demo] FAILED — expected a CONFLICT but received none.")
                return 1
    finally:
        router.stop()
        # Brief grace period so the router exits cleanly.
        try:
            await asyncio.wait_for(router_task, timeout=2)
        except asyncio.TimeoutError:
            router_task.cancel()
        await bus.close()
        await state.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
