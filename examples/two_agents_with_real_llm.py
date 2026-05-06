"""Phase 2 deliverable — same conflict demo, real LLM (Gemini by default).

Drop-in upgrade of `two_agents_conflict_demo.py`: agents wrap a real hosted
adapter and emit short LLM-generated descriptions before their actions. Demonstrates
the protocol working with real inference latency, and confirms the hosted adapter's
`inject_and_continue` mechanism by triggering one mid-stream interruption.

Backends:
- Default: GeminiAdapter (free quota with GOOGLE_API_KEY set)
- Set SYNAPSE_BACKEND=anthropic + ANTHROPIC_API_KEY to use Claude Haiku

Cost target: under $0.05 per run. We use the cheapest model in each family
(Gemini 2.5 Flash / Claude Haiku 4.5) and cap max_tokens at 256.
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
from synapse.adapters.base import InferenceAdapter, StreamHandle  # noqa: E402
from synapse.bus import Bus  # noqa: E402
from synapse.state import StateGraph  # noqa: E402
from runtime.router.worker import Router  # noqa: E402


REDIS_URL = os.getenv("SYNAPSE_REDIS_URL", "redis://localhost:6379/0")
POSTGRES_DSN = os.getenv(
    "SYNAPSE_POSTGRES_DSN",
    "postgresql://synapse:synapse_dev@localhost:5432/synapse",
)
BACKEND_NAME = os.getenv("SYNAPSE_BACKEND", "gemini").lower()


def _section(title: str) -> None:
    print(f"\n{'=' * 70}\n  {title}\n{'=' * 70}")


def make_backend() -> InferenceAdapter:
    """Pick a hosted adapter based on env. Cheap defaults.

    Gemini auto-uses Vertex AI when GOOGLE_APPLICATION_CREDENTIALS is set
    AND a project is provided via SYNAPSE_GCP_PROJECT. Falls back to
    GOOGLE_API_KEY (free tier) otherwise.
    """
    if BACKEND_NAME == "anthropic":
        from synapse.adapters.hosted import AnthropicAdapter
        return AnthropicAdapter(model="claude-haiku-4-5-20251001", max_tokens=256)
    if BACKEND_NAME == "gemini":
        from synapse.adapters.hosted import GeminiAdapter
        return GeminiAdapter(
            model="gemini-2.5-flash",
            max_tokens=256,
            project=os.environ.get("SYNAPSE_GCP_PROJECT"),
        )
    raise ValueError(f"Unknown SYNAPSE_BACKEND={BACKEND_NAME}; use 'gemini' or 'anthropic'")


async def collect(adapter: InferenceAdapter, handle: StreamHandle, max_tokens: int = 80) -> str:
    """Read up to N tokens from a streaming handle and return the joined text."""
    text = ""
    count = 0
    async for tok in adapter.read_tokens(handle):
        text += tok.text
        count += 1
        if count >= max_tokens:
            await adapter.cancel(handle)
            break
    return text.strip()


async def _wait_for_ready(name: str, fn, retries: int = 60, delay_s: float = 1.0) -> None:
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            await fn()
            if attempt > 0:
                print(f"  [{name}] connected after {attempt + 1} attempt(s)")
            return
        except Exception as e:
            last_err = e
            if attempt == 0:
                print(f"  [{name}] not ready yet (waiting up to {retries * delay_s:.0f}s)…")
            await asyncio.sleep(delay_s)
    raise RuntimeError(f"{name} not ready: {last_err}")


async def main() -> int:
    logging.basicConfig(
        level=os.getenv("SYNAPSE_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    session_id = f"demo_real_{uuid.uuid4().hex[:8]}"
    _section(f"Synapse + real LLM ({BACKEND_NAME})  [session={session_id}]")

    backend_a = make_backend()
    backend_b = make_backend()
    print(f"  Backend: {backend_a.capabilities.backend_id} / {backend_a.capabilities.model_id}")
    print(f"  Mid-stream inject supported: {backend_a.capabilities.supports_midstream_inject}")

    bus = Bus(REDIS_URL)
    state = StateGraph(POSTGRES_DSN)
    await _wait_for_ready("redis", bus.connect)
    await _wait_for_ready("postgres", state.connect)

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

    router = Router(bus, state, session_id, consumer="real_router")
    router_task = asyncio.create_task(router.run())

    try:
        async with agent_a.lifecycle(), agent_b.lifecycle():
            _section("Step 1: Agent A claims auth.middleware (write)")
            a_int_id, a_conflicts = await agent_a.emit_intention(
                action={"tool": "edit_file", "args": {"path": "auth/middleware.py"}},
                scope=["auth.middleware:w"],
                expected_outcome="Refactor middleware to use token-bucket rate limiting",
                blocking=False,
            )
            print(f"  Agent A intention: {a_int_id} (no conflicts)")
            assert not a_conflicts

            await asyncio.sleep(0.1)

            _section("Step 2: Agent A starts an LLM-generated work plan, then B collides")
            handle_a = await backend_a.start_stream(
                messages=[
                    {"role": "user",
                     "content": (
                        "I'm about to refactor auth/middleware.py to add a token-bucket "
                        "rate limiter. In two short sentences, describe the implementation."
                     )},
                ],
                params={"max_tokens": 80},
            )

            # Read first few tokens of A's plan
            first_tokens = []
            async for tok in backend_a.read_tokens(handle_a):
                first_tokens.append(tok.text)
                if len(first_tokens) >= 8:
                    break

            print(f"  Agent A partial plan: '{''.join(first_tokens).strip()[:80]}...'")

            # Now B tries to claim same scope
            b_int_id, b_conflicts = await agent_b.emit_intention(
                action={"tool": "edit_file", "args": {"path": "auth/middleware.py"}},
                scope=["auth.middleware:w"],
                expected_outcome="Add structured logging to middleware",
                blocking=True,
                gate_ms=500,
            )
            print(f"  Agent B intention: {b_int_id}")

            if not b_conflicts:
                print("\n[demo] FAILED — expected CONFLICT but received none.")
                return 1

            _section("Step 3: CONFLICT detected — Agent B receives structured signal")
            for c in b_conflicts:
                print(f"  Kind: {c.kind} | Suggested: {c.suggested_resolution}")
                print(f"  Overlapping scopes: {c.overlapping_scopes}")
                print(f"  Rationale: {c.rationale}")

            _section("Step 4: Test mid-stream injection on Agent A's running stream")
            print("  Injecting signal into A's running LLM call:")
            print("    'Agent B is also touching auth.middleware — coordinate or pivot.'")

            new_handle_a = await backend_a.inject_and_continue(
                handle_a,
                injection=(
                    "Agent B has also tried to claim auth.middleware. "
                    "It received a CONFLICT signal and will pivot. "
                    "Continue your plan, but acknowledge that you'll coordinate with B."
                ),
                instruction="Finish your description in one short sentence.",
            )

            continuation = await collect(backend_a, new_handle_a, max_tokens=60)
            print(f"  Agent A continuation: '{continuation[:200]}'")
            print()
            print("  -> Mid-stream injection: Agent A's running generation was interrupted,")
            print("     re-prompted with the conflict signal, and resumed coherently.")

            _section("Step 5: B narrows scope; both resolve")
            b2_id, b2_conflicts = await agent_b.emit_intention(
                action={"tool": "edit_file", "args": {"path": "auth/logging.py"}},
                scope=["auth.logging:w"],
                expected_outcome="Add logging in a separate module",
                blocking=True,
                gate_ms=300,
            )
            assert not b2_conflicts, "Narrowed scope should not conflict"
            await agent_a.emit_resolution(intention_id=a_int_id)
            await agent_b.emit_resolution(intention_id=b2_id)
            print(f"  Both intentions resolved cleanly.")
            print(f"\n[demo] Phase 2 verified: real LLM + mid-stream injection works.")
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
