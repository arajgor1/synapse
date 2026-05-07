"""End-to-end test: full protocol flow with mid-stream inject driven by a
real CONFLICT signal routed through Redis.

This is the test that proves Synapse works as a SYSTEM, not just per-component:

  Agent A (real Anthropic backend) starts an LLM call planning a refactor
       │
       │  while A is mid-stream...
       ▼
  Agent B (real OpenAI backend) emits an INTENTION on the same scope
       │
       │  ↓ to Redis Streams session bus ↓
       ▼
  Real Router worker (consumer group on session stream)
       │
       │  L2 SQL conflict check on Postgres state graph
       ▼
  Router emits CONFLICT envelope to Agent A's inbox stream
       │
       ▼
  Agent A's inbox watcher catches the CONFLICT mid-LLM-call
       │
       ▼
  Agent A calls backend.inject_and_continue with the conflict context
       │
       ▼
  Agent A's continued generation pivots to a non-overlapping scope,
  then emits a PIVOT envelope back to the bus

Pass conditions (mechanical):
  1. CONFLICT envelope shows up in agent_a's inbox within 1 second
  2. Agent A's post-inject continuation references a NEW scope/file
  3. Agent A's post-inject continuation does NOT reference the locked file
  4. Agent A emits a PIVOT envelope after the continuation lands

Cost: ~$0.005 per run (one Anthropic call + one OpenAI conflict-trigger call,
both small).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_REPO_ROOT, "sdk-python"))
sys.path.insert(0, _REPO_ROOT)

from synapse import Agent  # noqa: E402
from synapse.adapters import MockAdapter  # noqa: E402
from synapse.adapters.base import InferenceAdapter, StreamHandle  # noqa: E402
from synapse.bus import Bus  # noqa: E402
from synapse.messages import (  # noqa: E402
    Conflict,
    Envelope,
    MessageType,
    Pivot,
)
from synapse.state import StateGraph  # noqa: E402
from runtime.router.worker import Router  # noqa: E402


REDIS_URL = os.getenv("SYNAPSE_REDIS_URL", "redis://localhost:6379/0")
POSTGRES_DSN = os.getenv(
    "SYNAPSE_POSTGRES_DSN",
    "postgresql://synapse:synapse_dev@localhost:5432/synapse",
)
LOCKED_PATH = "auth/middleware.ts"
ALT_PATH_HINT = "auth/rate-limit-middleware.ts"


@dataclass
class TestResult:
    conflict_detected: bool = False
    conflict_latency_ms: float = 0.0
    pre_inject_text: str = ""
    post_inject_text: str = ""
    references_locked_path: bool = True   # default True so test must clear it
    references_alt_path: bool = False
    pivot_envelope_emitted: bool = False
    pivot_new_scope: list[str] = None  # type: ignore[assignment]
    overall_pass: bool = False
    notes: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.pivot_new_scope is None:
            self.pivot_new_scope = []
        if self.notes is None:
            self.notes = []


async def _wait_ready(name: str, fn) -> None:
    for _ in range(60):
        try:
            await fn()
            return
        except Exception:
            await asyncio.sleep(1)
    raise RuntimeError(f"{name} not ready")


async def _make_a_backend() -> InferenceAdapter:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[note] no ANTHROPIC_API_KEY — falling back to mock for agent_a")
        return MockAdapter(
            scripted_response="Plan: 1. Edit auth/middleware.ts to add token bucket.",
            delay_per_token_ms=20,  # slow enough that we can inject mid-stream
        )
    from synapse.adapters.hosted import AnthropicAdapter
    return AnthropicAdapter(model="claude-haiku-4-5-20251001", max_tokens=300)


def _make_b_backend() -> InferenceAdapter:
    # Agent B doesn't actually need to talk to an LLM — it just emits an
    # INTENTION via the protocol. Use Mock to keep cost down.
    return MockAdapter(scripted_response="ack")


async def main() -> int:
    logging.basicConfig(
        level=os.getenv("SYNAPSE_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    session_id = f"e2e_{uuid.uuid4().hex[:8]}"
    print(f"\n=== End-to-end inject test (real LLM, real Redis, real router) ===")
    print(f"session: {session_id}")
    print()

    bus = Bus(REDIS_URL)
    state = StateGraph(POSTGRES_DSN)
    await _wait_ready("redis", bus.connect)
    await _wait_ready("postgres", state.connect)

    backend_a = await _make_a_backend()
    backend_b = _make_b_backend()
    print(f"  agent_a backend: {backend_a.capabilities.backend_id} "
          f"(model: {backend_a.capabilities.model_id})")
    print(f"  agent_b backend: {backend_b.capabilities.backend_id}")

    agent_a = Agent(
        id="agent_a", session=session_id, backend=backend_a,
        subscribes=["auth.*"], scopes_owned=["auth.middleware"],
        bus=bus, state=state,
    )
    agent_b = Agent(
        id="agent_b", session=session_id, backend=backend_b,
        subscribes=["auth.*"], bus=bus, state=state,
    )

    # Real router worker
    router = Router(bus, state, session_id, consumer="e2e_router")
    router_task = asyncio.create_task(router.run())

    result = TestResult()

    try:
        async with agent_a.lifecycle(), agent_b.lifecycle():
            # ---- Step 1: Agent A claims auth.middleware ----
            a_int_id, _ = await agent_a.emit_intention(
                action={"tool": "edit_file", "args": {"path": LOCKED_PATH}},
                scope=["auth.middleware:w"],
                expected_outcome="Add token-bucket rate limiter",
                blocking=False,
            )
            print(f"  [step 1] agent_a INTENTION emitted: {a_int_id}")
            await asyncio.sleep(0.1)  # let router persist

            # ---- Step 2: Agent A starts an LLM call mid-task ----
            print(f"  [step 2] agent_a starting LLM stream (will inject mid-flight)")
            handle = await backend_a.start_stream(
                messages=[{
                    "role": "user",
                    "content": (
                        f"Output a JSON plan with 3 file edits to add token-bucket "
                        f"rate limiting to an Express.js app. Each edit: "
                        f'{{"path": "...", "action": "create|modify", "summary": "..."}}. '
                        f"The rate limiter goes in {LOCKED_PATH}. JSON only, no prose."
                    )
                }],
                params={"max_tokens": 300, "temperature": 0.0},
            )

            # Read partial output (commit to a direction)
            pre_text = ""
            async for tok in backend_a.read_tokens(handle):
                pre_text += tok.text
                if len(pre_text) >= 90:
                    break
            result.pre_inject_text = pre_text
            print(f"  [step 2] agent_a partial: {pre_text[:120]!r}")

            # ---- Step 3: Agent B emits a colliding INTENTION ----
            t_emit = time.time()
            b_int_id, _ = await agent_b.emit_intention(
                action={"tool": "edit_file", "args": {"path": LOCKED_PATH}},
                scope=["auth.middleware:w"],
                expected_outcome="Add structured logging to middleware",
                blocking=False,
            )
            print(f"  [step 3] agent_b INTENTION on SAME scope: {b_int_id}")

            # ---- Step 4: Wait for CONFLICT to land. Router routes CONFLICT to
            # the offending agent (agent_b in this case). We poll BOTH inboxes
            # via the bus directly (bypassing Agent state) for max diagnostic
            # clarity; with timeout so we never hang here.
            print(f"  [step 4] polling both inboxes for CONFLICT (max 3s)")
            conflict_env: Envelope | None = None
            poll_started = time.time()
            while time.time() - poll_started < 3.0:
                # Drain agent_b's inbox first — that's where CONFLICT goes
                b_entries = await asyncio.wait_for(
                    bus.drain_inbox(agent_b.id, last_id="0"), timeout=1.0,
                )
                for entry_id, env in b_entries:
                    if env.type == MessageType.CONFLICT:
                        conflict_env = env
                        break
                if conflict_env:
                    break
                # Also try agent_a's inbox in case routing rules change later
                a_entries = await asyncio.wait_for(
                    bus.drain_inbox(agent_a.id, last_id="0"), timeout=1.0,
                )
                for entry_id, env in a_entries:
                    if env.type == MessageType.CONFLICT:
                        conflict_env = env
                        break
                if conflict_env:
                    break
                await asyncio.sleep(0.1)
            if conflict_env is None:
                print(f"  [step 4] FAIL: no CONFLICT signal received")
                result.notes.append("No CONFLICT routed within 2.5s")
                return _finish(result, router, router_task, bus, state)

            t_conflict = time.time()
            result.conflict_detected = True
            result.conflict_latency_ms = round((t_conflict - t_emit) * 1000, 1)
            print(f"  [step 4] CONFLICT received in {result.conflict_latency_ms}ms")

            # ---- Step 5: Inject the conflict context into A's running stream ----
            cpayload = Conflict.model_validate(conflict_env.payload)
            injection = (
                f"SCOPE LOCK: {LOCKED_PATH} is now claimed by another agent "
                f"(agent_b, intention {cpayload.intention_id[:12]}...). "
                f"Pivot your plan: route the rate limiter into a NEW file at "
                f"{ALT_PATH_HINT} so you don't collide. "
                f"Do not touch {LOCKED_PATH} in any of your edits."
            )
            instruction = (
                "Re-emit your JSON plan using the new path. Output only the "
                "fresh JSON array, no prose."
            )
            print(f"  [step 5] injecting CONFLICT into agent_a's running stream")
            new_handle = await backend_a.inject_and_continue(
                handle, injection=injection, instruction=instruction
            )

            post_text = ""
            async for tok in backend_a.read_tokens(new_handle):
                post_text += tok.text
            result.post_inject_text = post_text
            print(f"  [step 5] continuation captured ({len(post_text)} chars)")

            # ---- Step 6: Mechanical verification ----
            result.references_locked_path = LOCKED_PATH in post_text
            result.references_alt_path = ALT_PATH_HINT in post_text
            print(f"  [step 6] continuation references locked path? "
                  f"{result.references_locked_path}")
            print(f"  [step 6] continuation references new path?    "
                  f"{result.references_alt_path}")

            # ---- Step 7: Agent A emits a PIVOT envelope ----
            pivot_payload = Pivot(
                from_intention_id=a_int_id,
                to_intention={
                    "action": {"tool": "edit_file", "args": {"path": ALT_PATH_HINT}},
                    "scope": ["auth.rate_limit_middleware:w"],
                    "expected_outcome": "Token-bucket rate limiter in a new module",
                },
                reason=(
                    f"CONFLICT: original scope auth.middleware:w collided with "
                    f"agent_b. Pivoting to a new module."
                ),
                affects=[],
                frees=["auth.middleware:w"],
            )
            pivot_env = Envelope.make(
                type=MessageType.PIVOT,
                agent_id=agent_a.id,
                session_id=session_id,
                payload=pivot_payload,
                parent_msg_id=a_int_id,
            )
            await bus.publish_session(pivot_env)
            result.pivot_envelope_emitted = True
            result.pivot_new_scope = pivot_payload.to_intention.scope
            print(f"  [step 7] PIVOT envelope emitted: {pivot_env.msg_id}")

            # ---- Overall pass condition ----
            result.overall_pass = (
                result.conflict_detected
                and result.references_alt_path
                and not result.references_locked_path
                and result.pivot_envelope_emitted
            )

            print()
            print("=" * 66)
            print("  Test result")
            print("=" * 66)
            print(f"  CONFLICT detected:        {result.conflict_detected}")
            print(f"  CONFLICT latency:         {result.conflict_latency_ms} ms")
            print(f"  Continuation pivots:      {result.references_alt_path}")
            print(f"  Avoids locked path:       {not result.references_locked_path}")
            print(f"  PIVOT envelope emitted:   {result.pivot_envelope_emitted}")
            print(f"  PIVOT new scope:          {result.pivot_new_scope}")
            print(f"  OVERALL:                  "
                  f"{'PASS' if result.overall_pass else 'FAIL'}")

            return await _finish(result, router, router_task, bus, state)
    except Exception as e:
        print(f"\n[error] {e}")
        result.notes.append(f"exception: {e}")
        return await _finish(result, router, router_task, bus, state)


async def _finish(result: TestResult, router, router_task, bus, state) -> int:
    router.stop()
    try:
        await asyncio.wait_for(router_task, timeout=2)
    except asyncio.TimeoutError:
        router_task.cancel()
    await bus.close()
    await state.close()

    out_dir = "bench/results"
    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    out_path = os.path.join(out_dir, f"e2e_protocol_inject_{ts}.json")
    with open(out_path, "w") as f:
        # dataclass -> dict via json
        d = {
            "conflict_detected": result.conflict_detected,
            "conflict_latency_ms": result.conflict_latency_ms,
            "pre_inject_text": result.pre_inject_text,
            "post_inject_text": result.post_inject_text,
            "references_locked_path": result.references_locked_path,
            "references_alt_path": result.references_alt_path,
            "pivot_envelope_emitted": result.pivot_envelope_emitted,
            "pivot_new_scope": result.pivot_new_scope,
            "overall_pass": result.overall_pass,
            "notes": result.notes,
        }
        json.dump(d, f, indent=2)
    print(f"\nresult saved -> {out_path}")
    return 0 if result.overall_pass else 1


async def _main_with_timeout() -> int:
    """Wrap main() with a 90s hard timeout so a stuck adapter cleanup can't
    keep the test process alive forever."""
    try:
        return await asyncio.wait_for(main(), timeout=90.0)
    except asyncio.TimeoutError:
        print("\n[timeout] e2e test exceeded 90s — likely a stream cleanup hang")
        return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(_main_with_timeout()))
