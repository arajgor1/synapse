"""``synapse demo`` — built-in 2-agent demo workload.

Runs a self-contained scenario against a running Synapse stack
(``synapse up`` first). Two agents claim the same scope concurrently;
the second one's INTENTION fires CONFLICT. No LLM required — uses the
universal ``synapse.intend()`` API directly with stub work.

Usage:
    synapse up                 # start Redis + Postgres
    synapse demo               # run the demo
    synapse status             # see what landed
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import uuid

import synapse


async def _agent(name: str, scope: str, session: str, work_ms: int) -> dict:
    """One agent: emit INTENTION, sleep (simulating work), check conflicts, exit."""
    started = time.time()
    async with synapse.intend(
        scope=[scope],
        agent=name,
        session=session,
        expected_outcome=f"demo work by {name}",
        blocking=True,
        gate_ms=300,
    ) as i:
        # Simulate the agent doing actual work
        await asyncio.sleep(work_ms / 1000)
        if i.has_conflicts:
            print(f"  [{name}] saw {len(i.conflicts)} CONFLICT(s) on {scope}")
        else:
            print(f"  [{name}] wrote to {scope} cleanly")
        i.set_state_diff({"work_done_ms": work_ms})
    elapsed = (time.time() - started) * 1000
    return {"name": name, "elapsed_ms": int(elapsed), "saw_conflicts": i.has_conflicts}


async def _run() -> int:
    bus_url = os.environ.get("SYNAPSE_REDIS_URL", "redis://localhost:6379/0")
    state_dsn = os.environ.get(
        "SYNAPSE_POSTGRES_DSN",
        "postgresql://synapse:synapse_dev@localhost:5432/synapse",
    )

    # Try to apply v0.1 migrations idempotently. If Postgres is down or unreachable,
    # the demo can still run in offline mode (intend() degrades gracefully).
    try:
        import asyncpg  # type: ignore
        from pathlib import Path
        bundled = Path(__file__).resolve().parent / "_data" / "migrations" / "0001_initial_schema.sql"
        if bundled.exists():
            conn = await asyncpg.connect(state_dsn)
            try:
                await conn.execute(bundled.read_text(encoding="utf-8"))
            finally:
                await conn.close()
    except Exception as e:
        print(f"  warning: could not apply migrations to {state_dsn}: {e}")
        print("  continuing in offline mode (intend() degrades gracefully)...")
        state_dsn = None

    session = f"synapse_demo_{uuid.uuid4().hex[:6]}"
    print(f"synapse demo — session={session}")

    # Bootstrap synapse runtime (no LLM needed for this demo)
    synapse.install(
        bus_url=bus_url,
        state_dsn=state_dsn,
        session_id=session,
    )

    # Start a router so CONFLICTs actually route to inboxes
    router_task = None
    if state_dsn is not None:
        try:
            from synapse.bus import Bus
            from synapse.state import StateGraph
            from runtime.router.worker import Router

            bus = Bus(bus_url)
            state = StateGraph(state_dsn)
            await bus.connect()
            await state.connect()
            router = Router(bus, state, session, consumer="synapse_demo_router")
            router_task = asyncio.create_task(router.run())
            await asyncio.sleep(0.3)
        except Exception as e:
            print(f"  warning: could not start router: {e}. Running without conflict routing.")

    # Two agents, same scope, racing
    SHARED = "demo.repo.fs.shared.py:w"
    print(f"  running 2 agents both claiming {SHARED!r}...")
    results = await asyncio.gather(
        _agent("alice", SHARED, session, work_ms=500),
        _agent("bob", SHARED, session, work_ms=500),
    )

    # Let the router catch up
    await asyncio.sleep(0.5)
    if router_task is not None:
        router.stop()
        try:
            await asyncio.wait_for(router_task, timeout=2)
        except asyncio.TimeoutError:
            router_task.cancel()

    saw_any = any(r["saw_conflicts"] for r in results)
    print()
    if saw_any:
        print("  ✓ at least one agent saw a CONFLICT — Synapse working as designed.")
    else:
        print(
            "  no CONFLICTs surfaced this run — likely the gate window closed before the "
            "router routed. Try `synapse demo` again, or `synapse status` to inspect."
        )

    print()
    print("  Inspect what landed:")
    print(f"    SYNAPSE_SESSION_ID={session}")
    print(f"    redis-cli xrange synapse:session:{session}:events - +")
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
