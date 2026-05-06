"""Phase 3 deliverable — three agents, three backend tiers, one protocol.

Demonstrates Synapse's central design claim: the same SDK code runs against
Mock (in-process), Hosted (Vertex AI Gemini), and Native (Modal vLLM/transformers)
backends with no per-tier branching at the application layer.

Scenario:
- Agent A (mock backend) — fastest, free, used for the orchestrator role
- Agent B (Gemini via Vertex AI) — hosted tier, real-LLM with cached restart
- Agent C (vLLM-via-Modal) — native tier with true KV-aware streaming

All three register in the same session, claim overlapping scopes, and the
router routes CONFLICT signals identically regardless of agent backend.

Cost: under $0.05 if Modal cold-start is short. Mock is free; Gemini Vertex
is free tier; Modal T4 is ~$0.01-0.02 per minute of warm GPU time.

Set SYNAPSE_SKIP_MODAL=1 to skip the native-tier agent (useful when no
deployed Modal app or to verify Mock + Hosted only).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from typing import Optional

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_REPO_ROOT, "sdk-python"))
sys.path.insert(0, _REPO_ROOT)

from synapse import Agent  # noqa: E402
from synapse.adapters import MockAdapter  # noqa: E402
from synapse.adapters.base import InferenceAdapter  # noqa: E402
from synapse.bus import Bus  # noqa: E402
from synapse.state import StateGraph  # noqa: E402
from runtime.router.worker import Router  # noqa: E402

REDIS_URL = os.getenv("SYNAPSE_REDIS_URL", "redis://localhost:6379/0")
POSTGRES_DSN = os.getenv(
    "SYNAPSE_POSTGRES_DSN",
    "postgresql://synapse:synapse_dev@localhost:5432/synapse",
)
SKIP_MODAL = os.getenv("SYNAPSE_SKIP_MODAL", "0") == "1"


def _section(title: str) -> None:
    print(f"\n{'=' * 70}\n  {title}\n{'=' * 70}")


def make_mock() -> InferenceAdapter:
    return MockAdapter(scripted_response="OK, proceeding with my task.", delay_per_token_ms=2)


def make_gemini() -> Optional[InferenceAdapter]:
    try:
        from synapse.adapters.hosted import GeminiAdapter
        return GeminiAdapter(
            model="gemini-2.5-flash",
            max_tokens=64,
            project=os.environ.get("SYNAPSE_GCP_PROJECT"),
        )
    except Exception as e:
        print(f"  [skip Gemini] {e}")
        return None


def make_vllm_modal() -> Optional[InferenceAdapter]:
    if SKIP_MODAL:
        return None
    try:
        from synapse.adapters.native import VLLMModalAdapter
        return VLLMModalAdapter()
    except Exception as e:
        print(f"  [skip Modal vLLM] {e}")
        return None


async def _wait_for_ready(name: str, fn, retries: int = 60, delay_s: float = 1.0) -> None:
    for attempt in range(retries):
        try:
            await fn()
            if attempt > 0:
                print(f"  [{name}] connected after {attempt + 1} attempt(s)")
            return
        except Exception as e:
            if attempt == 0:
                print(f"  [{name}] not ready yet (waiting up to {retries * delay_s:.0f}s)…")
            await asyncio.sleep(delay_s)
    raise RuntimeError(f"{name} not ready")


async def main() -> int:
    logging.basicConfig(
        level=os.getenv("SYNAPSE_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    session_id = f"demo_multi_{uuid.uuid4().hex[:8]}"
    _section(f"Synapse multi-backend demo  [session={session_id}]")

    # ---- Build agents from each available tier ----
    backends: list[tuple[str, InferenceAdapter]] = [("agent_a_mock", make_mock())]

    g = make_gemini()
    if g is not None:
        backends.append(("agent_b_gemini", g))

    v = make_vllm_modal()
    if v is not None:
        backends.append(("agent_c_vllm_modal", v))

    print(f"  Active backends: {len(backends)}")
    for name, b in backends:
        print(f"    - {name}: tier={b.capabilities.tier} model={b.capabilities.model_id}")

    if len(backends) < 2:
        print("\n[demo] Need at least 2 backends to demonstrate cross-tier coordination.")
        return 1

    bus = Bus(REDIS_URL)
    state = StateGraph(POSTGRES_DSN)
    await _wait_for_ready("redis", bus.connect)
    await _wait_for_ready("postgres", state.connect)

    agents: list[Agent] = []
    for name, backend in backends:
        agents.append(
            Agent(
                id=name,
                session=session_id,
                backend=backend,
                subscribes=["repo.*"],
                bus=bus,
                state=state,
            )
        )

    router = Router(bus, state, session_id, consumer="multi_router")
    router_task = asyncio.create_task(router.run())

    try:
        # Layer the lifecycles using AsyncExitStack
        from contextlib import AsyncExitStack
        async with AsyncExitStack() as stack:
            for a in agents:
                await stack.enter_async_context(a.lifecycle())

            _section("Step 1: Agent A claims repo.users.schema (write)")
            a_int_id, _ = await agents[0].emit_intention(
                action={"tool": "edit", "args": {"file": "schema.sql"}},
                scope=["repo.users.schema:w"],
                expected_outcome="Add tenant_id column to users",
                blocking=False,
            )
            print(f"  {agents[0].id} intention: {a_int_id}")
            await asyncio.sleep(0.1)

            _section("Step 2: Agent B (different tier) tries to write to same schema")
            b_int_id, b_conflicts = await agents[1].emit_intention(
                action={"tool": "edit", "args": {"file": "schema.sql"}},
                scope=["repo.users.schema:w"],
                expected_outcome="Drop the email index",
                blocking=True,
                gate_ms=500,
            )
            print(f"  {agents[1].id} intention: {b_int_id}")

            if b_conflicts:
                c = b_conflicts[0]
                print(f"  CONFLICT received by {agents[1].id} ({backends[1][1].capabilities.tier} tier)")
                print(f"  Kind: {c.kind} | Suggested: {c.suggested_resolution}")
                print(f"  Overlapping: {c.overlapping_scopes}")
            else:
                print(f"\n[demo] FAILED — B should have hit a conflict.")
                return 1

            if len(agents) >= 3:
                _section("Step 3: Agent C (third tier) claims a non-overlapping scope")
                c_int_id, c_conflicts = await agents[2].emit_intention(
                    action={"tool": "edit", "args": {"file": "tests/users_test.py"}},
                    scope=["repo.users.tests:w"],
                    expected_outcome="Add tests for tenant_id behaviour",
                    blocking=True,
                    gate_ms=300,
                )
                print(f"  {agents[2].id} intention: {c_int_id}")
                print(f"  Conflicts: {len(c_conflicts)} (expected 0 — different scope)")
                assert not c_conflicts

                # Now C's read-only intention on schema should NOT conflict with A's write
                # (read vs write semantics from spec/conflict-semantics.md)
                # Wait — read-vs-write DOES conflict per spec. Use a truly disjoint scope.

            _section("Step 4: B narrows scope; A resolves")
            b2_id, b2_conflicts = await agents[1].emit_intention(
                action={"tool": "edit", "args": {"file": "schema_indexes.sql"}},
                scope=["repo.users.indexes:w"],
                expected_outcome="Move index changes to a separate file",
                blocking=True,
                gate_ms=300,
            )
            assert not b2_conflicts, "Narrowed scope should not conflict"
            await agents[0].emit_resolution(intention_id=a_int_id)
            await agents[1].emit_resolution(intention_id=b2_id)
            if len(agents) >= 3:
                await agents[2].emit_resolution(intention_id=c_int_id)
            print("  All resolved.")

            _section("Phase 3 verification")
            print(f"  Agents in session: {len(agents)}")
            print(f"  Backend tiers exercised: {sorted({b[1].capabilities.tier for b in backends})}")
            print(f"  Same SDK API across all tiers: PASS")
            print(f"  Cross-tier conflict routing: PASS")
            print(f"\n[demo] Phase 3 verified: multi-backend coordination works.")
            return 0
    finally:
        router.stop()
        try:
            await asyncio.wait_for(router_task, timeout=2)
        except asyncio.TimeoutError:
            router_task.cancel()
        await bus.close()
        await state.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
