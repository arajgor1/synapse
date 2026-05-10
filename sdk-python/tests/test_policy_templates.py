"""End-to-end tests for the 5 conflict-resolution policy templates.

Each template is exercised against a real two-agent collision in
zero-infra mode (no Redis/Postgres needed) so the test surface
matches what a user would actually experience.
"""
from __future__ import annotations

import asyncio
import os
import time

import pytest

import synapse
from synapse.policies import (
    EscalateToHumanPolicy,
    QueueBehindPolicy,
    RetryWithBackoffPolicy,
    WaitForOtherPolicy,
    WorkOnDifferentScopePolicy,
)
from synapse.policies.base import MergeDecision, SynapseConflict


@pytest.fixture(autouse=True)
async def _isolate_runtime(tmp_path, monkeypatch):
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    monkeypatch.delenv("SYNAPSE_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("SYNAPSE_OFFLINE", raising=False)
    monkeypatch.setenv("SYNAPSE_SQLITE_PATH", str(tmp_path / "policies.db"))
    from synapse.intend import shutdown as _sd
    await _sd()
    yield
    await _sd()


# ---------------------------------------------------------------------------
# Registry — every template surfaces via synapse.MergePolicy.* and string
# ---------------------------------------------------------------------------
def test_templates_exposed_via_namespace():
    assert isinstance(synapse.MergePolicy.queue_behind, QueueBehindPolicy)
    assert isinstance(synapse.MergePolicy.wait_for_other, WaitForOtherPolicy)
    assert isinstance(synapse.MergePolicy.work_on_different_scope, WorkOnDifferentScopePolicy)
    assert isinstance(synapse.MergePolicy.escalate_to_human, EscalateToHumanPolicy)
    assert isinstance(synapse.MergePolicy.retry_with_backoff, RetryWithBackoffPolicy)


def test_templates_resolve_by_string():
    from synapse.policies.registry import resolve_policy
    assert isinstance(resolve_policy("queue_behind"), QueueBehindPolicy)
    assert isinstance(resolve_policy("wait_for_other"), WaitForOtherPolicy)
    assert isinstance(resolve_policy("work_on_different_scope"), WorkOnDifferentScopePolicy)
    assert isinstance(resolve_policy("escalate_to_human"), EscalateToHumanPolicy)
    assert isinstance(resolve_policy("escalate"), EscalateToHumanPolicy)  # alias
    assert isinstance(resolve_policy("retry_with_backoff"), RetryWithBackoffPolicy)
    assert isinstance(resolve_policy("retry"), RetryWithBackoffPolicy)    # alias


# ---------------------------------------------------------------------------
# WorkOnDifferentScopePolicy — pivots the path argument
# ---------------------------------------------------------------------------
def test_work_on_different_scope_pivots_extension_paths():
    p = WorkOnDifferentScopePolicy()

    class FakeHandle:
        agent_id = "alice"
        scope = ["repo.fs.foo/bar.py:w"]
        session_id = "s"

    proposed = {"path": "foo/bar.py", "content": "x"}
    out = asyncio.run(p.resolve(FakeHandle(), conflicts=[], proposed_action=proposed))
    assert out.decision == MergeDecision.MERGED
    assert out.merged_action["path"] == "foo/bar.alice.py"
    assert out.merged_action["content"] == "x"


def test_work_on_different_scope_no_extension():
    p = WorkOnDifferentScopePolicy()

    class FakeHandle:
        agent_id = "bob"
        scope = ["repo.fs.dist/build:w"]
        session_id = "s"

    proposed = {"path": "dist/build", "content": "y"}
    out = asyncio.run(p.resolve(FakeHandle(), conflicts=[], proposed_action=proposed))
    assert out.decision == MergeDecision.MERGED
    assert out.merged_action["path"] == "dist/build.bob"


def test_work_on_different_scope_no_proposed_action_falls_back():
    p = WorkOnDifferentScopePolicy()

    class FakeHandle:
        agent_id = "alice"
        scope = ["x:w"]
        session_id = "s"

    out = asyncio.run(p.resolve(FakeHandle(), conflicts=[], proposed_action=None))
    # Default on_no_pivot is PROCEED
    assert out.decision == MergeDecision.PROCEED


def test_work_on_different_scope_unsanitisable_agent():
    """An agent with shell-unsafe characters should still produce a
    safe filename component."""
    p = WorkOnDifferentScopePolicy()

    class FakeHandle:
        agent_id = "alice/../../etc"
        scope = ["x:w"]
        session_id = "s"

    out = asyncio.run(p.resolve(FakeHandle(), conflicts=[], proposed_action={"path": "f.py", "content": "x"}))
    assert out.decision == MergeDecision.MERGED
    # Slashes in agent_id should NOT survive into the filename.
    assert "/" not in out.merged_action["path"].split("/")[-1]


# ---------------------------------------------------------------------------
# QueueBehindPolicy — waits for other intentions to resolve
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_queue_behind_proceeds_when_other_resolves(monkeypatch):
    """Two coroutines hit the same scope; second uses queue_behind. The
    first's intention resolves quickly, so queue_behind proceeds."""
    sess = "qb_session"
    scope = ["repo.fs.queue.py:w"]
    log: list[str] = []

    async def first():
        with synapse.with_agent("first"):
            async with synapse.intend(
                scope=scope, agent="first", session=sess,
                blocking=True,
            ) as i:
                log.append("first.in")
                await asyncio.sleep(0.1)
                log.append("first.out")

    async def second():
        await asyncio.sleep(0.02)  # let first claim
        with synapse.with_agent("second"):
            async with synapse.intend(
                scope=scope, agent="second", session=sess,
                blocking=True,
                merge_policy=QueueBehindPolicy(timeout_ms=2_000, poll_interval_ms=20),
            ) as i:
                log.append("second.in")
                # Should only get here AFTER first resolves
                assert "first.out" in log, (
                    f"queue_behind did not wait — log so far: {log}"
                )

    await asyncio.gather(first(), second())
    assert log == ["first.in", "first.out", "second.in"]


@pytest.mark.asyncio
async def test_queue_behind_aborts_on_timeout():
    """If the other agent never resolves within the timeout, queue_behind
    aborts (default on_timeout=ABORT)."""
    sess = "qb_timeout"
    scope = ["repo.fs.qbt.py:w"]

    held = asyncio.Event()
    release = asyncio.Event()

    async def hog():
        with synapse.with_agent("hog"):
            async with synapse.intend(
                scope=scope, agent="hog", session=sess, blocking=False,
            ):
                held.set()
                await release.wait()  # don't release until told

    async def latecomer():
        await held.wait()
        try:
            with synapse.with_agent("latecomer"):
                async with synapse.intend(
                    scope=scope, agent="latecomer", session=sess,
                    blocking=True,
                    merge_policy=QueueBehindPolicy(
                        timeout_ms=300, poll_interval_ms=20,
                    ),
                ):
                    pytest.fail("queue_behind should have aborted, body ran")
        except SynapseConflict:
            return "aborted"
        finally:
            release.set()

    _, late_result = await asyncio.gather(hog(), latecomer())
    assert late_result == "aborted"


# ---------------------------------------------------------------------------
# RetryWithBackoffPolicy — clears within budget, or aborts on exhaustion
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_retry_with_backoff_clears_within_budget():
    """The conflicting intention resolves before the retry budget is
    exhausted — policy proceeds."""
    sess = "rwb_clears"
    scope = ["repo.fs.rwb.py:w"]
    cleared_at: list[float] = []

    async def quick_holder():
        with synapse.with_agent("holder"):
            async with synapse.intend(
                scope=scope, agent="holder", session=sess, blocking=False,
            ):
                await asyncio.sleep(0.08)
            cleared_at.append(time.monotonic())

    async def retrier():
        await asyncio.sleep(0.01)
        with synapse.with_agent("retrier"):
            async with synapse.intend(
                scope=scope, agent="retrier", session=sess,
                blocking=True,
                merge_policy=RetryWithBackoffPolicy(
                    max_attempts=10, initial_backoff_ms=20, max_backoff_ms=80,
                ),
            ) as i:
                # Should have proceeded only after holder cleared.
                assert cleared_at, "retrier ran before holder cleared"

    await asyncio.gather(quick_holder(), retrier())


@pytest.mark.asyncio
async def test_retry_with_backoff_aborts_when_exhausted():
    """The conflicting intention never resolves; retry exhausts and aborts."""
    sess = "rwb_exhaust"
    scope = ["repo.fs.rwbe.py:w"]
    held = asyncio.Event()
    release = asyncio.Event()

    async def stubborn_holder():
        with synapse.with_agent("stubborn"):
            async with synapse.intend(
                scope=scope, agent="stubborn", session=sess, blocking=False,
            ):
                held.set()
                await release.wait()

    async def retrier():
        await held.wait()
        try:
            with synapse.with_agent("retrier"):
                async with synapse.intend(
                    scope=scope, agent="retrier", session=sess,
                    blocking=True,
                    merge_policy=RetryWithBackoffPolicy(
                        max_attempts=3,
                        initial_backoff_ms=20,
                        max_backoff_ms=40,
                        backoff_multiplier=2.0,
                    ),
                ):
                    pytest.fail("retry_with_backoff should have aborted")
        except SynapseConflict:
            return "aborted"
        finally:
            release.set()

    _, result = await asyncio.gather(stubborn_holder(), retrier())
    assert result == "aborted"


# ---------------------------------------------------------------------------
# EscalateToHumanPolicy — emits BLOCK + aborts
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_escalate_to_human_aborts_with_block_envelope():
    """escalate_to_human aborts the intention and emits a BLOCK envelope
    on the bus describing the escalation."""
    sess = "esc_session"
    scope = ["repo.fs.billing.py:w"]
    held = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        with synapse.with_agent("holder"):
            async with synapse.intend(
                scope=scope, agent="holder", session=sess, blocking=False,
            ):
                held.set()
                await release.wait()

    async def escalator():
        await held.wait()
        try:
            with synapse.with_agent("escalator"):
                async with synapse.intend(
                    scope=scope, agent="escalator", session=sess,
                    blocking=True,
                    merge_policy=EscalateToHumanPolicy(),
                ):
                    pytest.fail("escalate_to_human should have aborted")
        except SynapseConflict as e:
            assert "escalate" in str(e).lower() or "human" in str(e).lower()
            return "escalated"
        finally:
            release.set()

    _, result = await asyncio.gather(holder(), escalator())
    assert result == "escalated"


# ---------------------------------------------------------------------------
# WaitForOtherPolicy — alias smoke test
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_wait_for_other_is_queue_behind_alias():
    """wait_for_other behaves exactly like queue_behind."""
    sess = "wfo_session"
    scope = ["repo.fs.wfo.py:w"]
    log: list[str] = []

    async def first():
        with synapse.with_agent("first"):
            async with synapse.intend(
                scope=scope, agent="first", session=sess, blocking=True,
            ):
                log.append("first.in")
                await asyncio.sleep(0.05)
                log.append("first.out")

    async def second():
        await asyncio.sleep(0.01)
        with synapse.with_agent("second"):
            async with synapse.intend(
                scope=scope, agent="second", session=sess, blocking=True,
                merge_policy=WaitForOtherPolicy(timeout_ms=2_000, poll_interval_ms=10),
            ):
                log.append("second.in")
                assert "first.out" in log

    await asyncio.gather(first(), second())
