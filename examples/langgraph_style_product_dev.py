"""LangGraph-style product-dev demo using @synapse_node decorator.

Demonstrates how a LangGraph workflow gets coordination by decorating
nodes with @synapse_node. Nodes that touch overlapping scopes raise
SynapseConflict, which a conditional edge can route to a pivot node.

We don't import langgraph here — we duck-type a graph as a list of
async node functions. Real LangGraph users use:

    from langgraph.graph import StateGraph
    builder = StateGraph(MyState)
    builder.add_node("plan", planner_with_synapse)
    builder.add_node("implement", implementer_with_synapse)
    builder.add_conditional_edges(
        "implement",
        lambda state: "pivot" if state.get("conflicted") else "review",
        {"pivot": "pivot_node", "review": "reviewer"},
    )

Run:
  docker compose up -d
  python examples/langgraph_style_product_dev.py
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

from synapse.integrations import synapse_node  # noqa: E402
from synapse.integrations.langgraph_integration import SynapseConflict  # noqa: E402


async def main() -> int:
    session_id = f"lg_{uuid.uuid4().hex[:6]}"
    os.environ["SYNAPSE_SESSION_ID"] = session_id
    print(f"\n=== LangGraph-style product-dev demo  [session={session_id}] ===\n")

    # Spin up an in-process router so synapse_node's gate can detect conflicts.
    # Without this, intentions land in the state graph but no CONFLICT is
    # emitted to inboxes (the L2 router is what does that).
    from synapse.bus import Bus
    from synapse.state import StateGraph
    from runtime.router.worker import Router

    router_bus = Bus()
    router_state = StateGraph(
        os.getenv("SYNAPSE_POSTGRES_DSN",
                  "postgresql://synapse:synapse_dev@localhost:5432/synapse"),
    )
    await router_bus.connect()
    await router_state.connect()
    router = Router(router_bus, router_state, session_id, consumer="lg_demo_router")
    router_task = asyncio.create_task(router.run())
    print("[router] started in-process router for L2 conflict detection\n")

    # ---- Node 1: planner — claims repo.plan:w ----
    @synapse_node(
        agent_id="planner",
        scope=["repo.plan:w"],
        expected_outcome="Produce implementation plan",
        gate_ms=200,
    )
    async def planner(state: dict) -> dict:
        await asyncio.sleep(0.1)
        return {**state, "plan": "1. Add User model. 2. Add /signup endpoint. 3. Tests."}

    # ---- Node 2: implementer — claims repo.code:w ----
    @synapse_node(
        agent_id="implementer",
        scope=["repo.code:w"],
        expected_outcome="Implement the plan",
        gate_ms=200,
    )
    async def implementer(state: dict) -> dict:
        await asyncio.sleep(0.2)
        return {**state, "code": "class User(Base): ..."}

    # ---- Node 3: alt_implementer — also claims repo.code:w (CONFLICT) ----
    @synapse_node(
        agent_id="alt_implementer",
        scope=["repo.code:w"],
        expected_outcome="Implement an alternate version",
        gate_ms=500,
        blocking=True,
    )
    async def alt_implementer(state: dict) -> dict:
        return {**state, "alt_code": "class User(Base): pass"}

    # ---- Node 4: reviewer — claims repo.review:w ----
    @synapse_node(
        agent_id="reviewer",
        scope=["repo.review:w"],
        expected_outcome="Review the implementation",
        gate_ms=200,
    )
    async def reviewer(state: dict) -> dict:
        await asyncio.sleep(0.05)
        return {**state, "review": "LGTM"}

    # ---- Node 5: pivot — runs when implementer conflicts ----
    @synapse_node(
        agent_id="pivot_implementer",
        scope=["repo.code.alt:w"],   # different scope on the pivot path
        expected_outcome="Implement on a non-overlapping scope",
        gate_ms=200,
    )
    async def pivot_implementer(state: dict) -> dict:
        return {**state, "pivot_code": "module: alternate_user.py"}

    # ---- Run the "graph" sequentially with parallel branches ----
    state: dict = {}

    print("[node 1] planner")
    state = await planner(state)
    print(f"  state.plan: {state['plan']}")

    # Run implementer + alt_implementer concurrently — they collide
    print("\n[nodes 2 + 3] implementer + alt_implementer (concurrent, same scope)")
    impl_task = asyncio.create_task(implementer(state))
    await asyncio.sleep(0.05)  # let implementer claim first

    try:
        alt_state = await alt_implementer(state)
        print(f"  alt_implementer ran (no conflict): keys={list(alt_state)}")
        state = alt_state
    except SynapseConflict as e:
        print(f"  alt_implementer hit SynapseConflict: {e}")
        print(f"  -> conditional edge: routing to pivot_implementer")
        state = await pivot_implementer(state)
        print(f"  pivot_implementer succeeded: pivot_code={state.get('pivot_code')}")

    state = await impl_task  # wait for the original implementer
    print(f"  implementer done: code={state.get('code')[:40]!r}...")

    print("\n[node 4] reviewer")
    state = await reviewer(state)
    print(f"  state.review: {state['review']}")

    print("\n=== Final state ===")
    for k, v in state.items():
        v_str = str(v)
        if len(v_str) > 80:
            v_str = v_str[:80] + "..."
        print(f"  {k}: {v_str}")

    print("\nTakeaway: nodes participating in coordination need only the")
    print("@synapse_node decorator. Existing graph topology is unchanged;")
    print("conditional edges route on the SynapseConflict exception.")

    # Cleanup: stop the in-process router
    router.stop()
    try:
        await asyncio.wait_for(router_task, timeout=2)
    except asyncio.TimeoutError:
        router_task.cancel()
    await router_bus.close()
    await router_state.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
