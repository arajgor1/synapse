"""CrewAI-style product-dev demo using synapse_task integration.

This example shows how a real CrewAI crew (or any framework with a
Task.execute pattern) gets coordination "for free" via Synapse:
just wrap your tasks with `synapse_task(...)` and they participate
in scope conflict detection without changing your task code.

We don't import crewai here (heavy dep) — we DUCK-TYPE a CrewAI Task
shape (`.execute_async()` method) so the integration's monkey-patching
path is exercised. The synapse_task wrapper would work identically
with a real CrewAI Task.

Scenario: 3 agents (architect, builder, reviewer) building a feature.
Architect claims `repo.models:w` first. The builder also tries to claim
the same scope mid-task — synapse_task catches the conflict, raises
SynapseConflict, and the builder's exception handler can route to a
pivot path.

Run:
  docker compose up -d
  python examples/crewai_style_product_dev.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_REPO_ROOT, "sdk-python"))
sys.path.insert(0, _REPO_ROOT)

from synapse.integrations import synapse_task  # noqa: E402
from synapse.integrations.langgraph_integration import SynapseConflict  # noqa: E402


# ---------------------------------------------------------------------------
# Fake CrewAI-Task shape — just .execute_async() and .description
# ---------------------------------------------------------------------------
class FakeCrewTask:
    def __init__(self, description: str, work_fn):
        self.description = description
        self._work = work_fn
        self.last_output = None

    async def execute_async(self, *args, **kwargs):
        out = await self._work(*args, **kwargs)
        self.last_output = out
        return out

    def execute_sync(self, *args, **kwargs):
        return asyncio.run(self.execute_async(*args, **kwargs))


# ---------------------------------------------------------------------------
async def main() -> int:
    session_id = f"crew_{uuid.uuid4().hex[:6]}"
    os.environ["SYNAPSE_SESSION_ID"] = session_id
    print(f"\n=== CrewAI-style product-dev demo  [session={session_id}] ===\n")

    # Spin up an in-process router so synapse_task's gate can detect conflicts.
    from synapse.bus import Bus
    from synapse.state import StateGraph
    from runtime.router.worker import Router
    rb = Bus()
    rs = StateGraph(
        os.getenv("SYNAPSE_POSTGRES_DSN",
                  "postgresql://synapse:synapse_dev@localhost:5432/synapse"),
    )
    await rb.connect()
    await rs.connect()
    router = Router(rb, rs, session_id, consumer="crew_demo_router")
    router_task = asyncio.create_task(router.run())
    print("[router] in-process router started\n")

    # Define raw tasks (this is what crewai users have today)
    async def architect_work():
        await asyncio.sleep(0.1)
        return {
            "spec": "URL model with fields: short_code, original_url, created_at",
            "claimed_scope": "repo.models:w",
        }

    async def builder_work():
        await asyncio.sleep(0.1)
        return {
            "code": "class URL(Base): short_code = Column(String(8), primary_key=True); original_url = Column(String)",
            "claimed_scope": "repo.models:w",  # same scope as architect — collision!
        }

    async def reviewer_work():
        await asyncio.sleep(0.1)
        return {
            "review": "LGTM — model fields look reasonable",
            "claimed_scope": "repo.tests:r",
        }

    # Build raw tasks (CrewAI Task duck-type)
    raw_arch = FakeCrewTask("Design URL data model", architect_work)
    raw_build = FakeCrewTask("Implement URL model class", builder_work)
    raw_review = FakeCrewTask("Review the URL model", reviewer_work)

    # Wrap with synapse_task — this is the only line the user adds
    print("[1] Wrapping CrewAI Tasks with synapse_task(...)")
    arch_task = synapse_task(
        agent_id="architect",
        scope=["repo.models:w"],
        expected_outcome="Design URL data model",
        gate_ms=200,
    )(raw_arch)

    build_task = synapse_task(
        agent_id="builder",
        scope=["repo.models:w"],   # same scope -> CONFLICT expected
        expected_outcome="Implement URL model class",
        gate_ms=500,
    )(raw_build)

    review_task = synapse_task(
        agent_id="reviewer",
        scope=["repo.tests:r"],     # disjoint -> no conflict
        expected_outcome="Review the URL model",
        gate_ms=200,
    )(raw_review)

    # Run architect first — claims repo.models:w
    print("\n[2] Architect runs first, claims repo.models:w")
    arch_out = await arch_task.execute_async()
    print(f"    architect output: {arch_out}")

    # Run reviewer — disjoint scope, no conflict expected
    print("\n[3] Reviewer runs — disjoint scope (repo.tests:r), no conflict")
    rev_out = await review_task.execute_async()
    print(f"    reviewer output: {rev_out}")

    # Run builder — same scope as architect, ARCH already resolved? Let's check
    # In our test, architect's intention is RESOLVED (synapse_task emits
    # RESOLUTION on success). So builder's claim should succeed.
    print("\n[4] Builder runs after architect resolved")
    try:
        build_out = await build_task.execute_async()
        print(f"    builder output: {build_out}")
        print(f"    -> builder ran cleanly (architect already RESOLVED)")
    except SynapseConflict as e:
        print(f"    SynapseConflict: {e}")

    # Now demonstrate the conflict path: re-define a NEW scope-overlapping
    # task while another is still active.
    print("\n[5] Now: two tasks claim the SAME scope concurrently")

    async def slow_arch_work():
        await asyncio.sleep(2.0)  # holds the scope for 2s
        return "slow architect done"

    async def quick_overlapping_work():
        await asyncio.sleep(0.1)
        return "quick collider"

    raw_slow = FakeCrewTask("Slow concurrent work on auth.middleware", slow_arch_work)
    raw_quick = FakeCrewTask("Quick collider on auth.middleware", quick_overlapping_work)

    slow_task = synapse_task(
        agent_id="slow_agent",
        scope=["auth.middleware:w"],
        expected_outcome="Hold the scope for 2s",
        gate_ms=100,
    )(raw_slow)

    quick_task = synapse_task(
        agent_id="quick_agent",
        scope=["auth.middleware:w"],
        expected_outcome="Try to claim the same scope",
        blocking=True,
        gate_ms=500,
    )(raw_quick)

    # Start slow first, give it 0.2s to claim, then start quick
    slow_future = asyncio.create_task(slow_task.execute_async())
    await asyncio.sleep(0.3)

    print("    slow_agent is holding auth.middleware:w; quick_agent attempts...")
    try:
        quick_out = await quick_task.execute_async()
        print(f"    quick_agent ran: {quick_out}  (no conflict caught)")
    except SynapseConflict as e:
        print(f"    SynapseConflict caught: {e}")
        print(f"    -> quick_agent code can now route to a pivot path")

    # Wait for slow to finish
    slow_out = await slow_future
    print(f"    slow_agent done: {slow_out}")

    print("\n=== Demo complete ===")
    print("Takeaway: synapse_task wraps any CrewAI Task (or callable) with no")
    print("changes to the task body. Conflicts surface as SynapseConflict")
    print("exceptions — your existing exception-handling can route to pivots.")

    # Cleanup
    router.stop()
    try:
        await asyncio.wait_for(router_task, timeout=2)
    except asyncio.TimeoutError:
        router_task.cancel()
    await rb.close()
    await rs.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
