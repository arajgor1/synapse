"""Tests for synapse.agent_context — the per-task ContextVar attribution.

The pre-v0.2.3 attribution scheme used os.environ["SYNAPSE_AGENT_ID"]
which races under asyncio.gather (last writer wins, both attributions
collapse to the same name). These tests assert the new ContextVar-based
scheme is race-free under exactly that scenario.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from synapse.agent_context import (
    _AGENT_CTX,
    current_agent_id,
    set_agent_context,
    reset_agent_context,
    with_agent,
)


def test_current_agent_id_default_when_unset(monkeypatch):
    monkeypatch.delenv("SYNAPSE_AGENT_ID", raising=False)
    monkeypatch.delenv("SYNAPSE_DEFAULT_AGENT_ID", raising=False)
    assert current_agent_id() == "synapse_agent"
    assert current_agent_id(default="x") == "x"


def test_env_var_resolution(monkeypatch):
    monkeypatch.delenv("SYNAPSE_AGENT_ID", raising=False)
    monkeypatch.setenv("SYNAPSE_DEFAULT_AGENT_ID", "from_default_env")
    assert current_agent_id(default="x") == "from_default_env"
    monkeypatch.setenv("SYNAPSE_AGENT_ID", "from_env")
    assert current_agent_id(default="x") == "from_env"


def test_contextvar_beats_env(monkeypatch):
    monkeypatch.setenv("SYNAPSE_AGENT_ID", "from_env")
    token = set_agent_context("from_ctx")
    try:
        assert current_agent_id() == "from_ctx"
    finally:
        reset_agent_context(token)
    # After reset, env wins again
    assert current_agent_id() == "from_env"


def test_with_agent_restores_previous():
    token = set_agent_context("outer")
    try:
        assert current_agent_id() == "outer"
        with with_agent("inner"):
            assert current_agent_id() == "inner"
        assert current_agent_id() == "outer"
    finally:
        reset_agent_context(token)


@pytest.mark.asyncio
async def test_no_race_under_gather(monkeypatch):
    """The motivating bug: two coroutines run via asyncio.gather, each
    sets a different agent_id, and reads its own attribution back. The
    old env-var scheme produced both reads = last writer."""
    monkeypatch.delenv("SYNAPSE_AGENT_ID", raising=False)
    monkeypatch.delenv("SYNAPSE_DEFAULT_AGENT_ID", raising=False)

    async def worker(name: str, delay: float) -> str:
        with with_agent(name):
            # Sleep AFTER setting; under env-var racing the other coro
            # could overwrite during this window.
            await asyncio.sleep(delay)
            # Read inside the same task — should always be `name`.
            return current_agent_id()

    results = await asyncio.gather(
        worker("alice", 0.05),
        worker("bob",   0.01),
        worker("carol", 0.03),
    )
    assert results == ["alice", "bob", "carol"]


@pytest.mark.asyncio
async def test_propagates_through_create_task():
    async def child() -> str:
        return current_agent_id()

    with with_agent("parent_agent"):
        # asyncio.create_task copies the current context — child should
        # see the parent's agent_id.
        result = await asyncio.create_task(child())
    assert result == "parent_agent"


@pytest.mark.asyncio
async def test_propagates_through_to_thread():
    """asyncio.to_thread uses contextvars.copy_context() under the hood,
    so framework adapters that bridge sync→async via to_thread keep the
    correct attribution per task."""

    def sync_reader() -> str:
        return current_agent_id()

    with with_agent("thread_agent"):
        result = await asyncio.to_thread(sync_reader)
    assert result == "thread_agent"


@pytest.mark.asyncio
async def test_concurrent_distinct_attribution_high_volume(monkeypatch):
    """Stress the gather case: 50 concurrent tasks each setting a unique
    name, every read must equal that task's own name (zero misattributions)."""
    monkeypatch.delenv("SYNAPSE_AGENT_ID", raising=False)

    async def w(i: int) -> tuple[int, str]:
        with with_agent(f"agent_{i:02d}"):
            await asyncio.sleep(0.001 * (i % 5))
            return (i, current_agent_id())

    out = await asyncio.gather(*[w(i) for i in range(50)])
    misattributed = [(i, name) for i, name in out if name != f"agent_{i:02d}"]
    assert misattributed == [], f"Misattribution under load: {misattributed}"
