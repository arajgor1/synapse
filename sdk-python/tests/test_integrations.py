"""Unit tests for framework integrations.

These are unit-level — the integrations are tested without spinning up
real Bus/StateGraph. We patch _ensure_agent to return a fake Agent that
records calls.
"""

from __future__ import annotations

import asyncio
import sys
import os
from unittest.mock import AsyncMock, MagicMock

import pytest


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO_ROOT)


class _FakeAgent:
    def __init__(self) -> None:
        self.intentions: list[dict] = []
        self.resolutions: list[dict] = []
        self._next_conflicts = []  # populate to simulate CONFLICT

    async def emit_intention(self, **kwargs):
        self.intentions.append(kwargs)
        return ("01HQ" + "0" * 22, list(self._next_conflicts))

    async def emit_resolution(self, **kwargs):
        self.resolutions.append(kwargs)


@pytest.fixture
def fake_agent(monkeypatch):
    fa = _FakeAgent()

    async def fake_ensure(**kwargs):
        return fa

    # Both LangGraph and CrewAI integrations use this helper
    from synapse.integrations import langgraph_integration as lg
    from synapse.integrations import crewai_integration as ca

    monkeypatch.setattr(lg, "_ensure_agent", fake_ensure)
    monkeypatch.setattr(ca, "_ensure_agent", fake_ensure)
    return fa


class TestLangGraphIntegration:
    @pytest.mark.asyncio
    async def test_node_emits_intention_and_resolution_on_success(self, fake_agent):
        from synapse.integrations import synapse_node

        @synapse_node(
            agent_id="a1",
            scope=["x.y:w"],
            expected_outcome="t",
            session_id="s1",
            blocking=False,
        )
        async def node(state: dict) -> dict:
            return {**state, "ran": True}

        result = await node({"input": 1})
        assert result == {"input": 1, "ran": True}
        assert len(fake_agent.intentions) == 1
        assert len(fake_agent.resolutions) == 1
        assert fake_agent.resolutions[0]["outcome"] == "success"

    @pytest.mark.asyncio
    async def test_node_emits_failure_resolution_on_exception(self, fake_agent):
        from synapse.integrations import synapse_node

        @synapse_node(
            agent_id="a1", scope=["x.y:w"], expected_outcome="t",
            session_id="s1", blocking=False,
        )
        async def node(state: dict) -> dict:
            raise ValueError("nope")

        with pytest.raises(ValueError):
            await node({})
        assert len(fake_agent.resolutions) == 1
        assert fake_agent.resolutions[0]["outcome"] == "failure"

    @pytest.mark.asyncio
    async def test_node_raises_synapse_conflict_when_gate_returns_conflicts(
        self, fake_agent,
    ):
        from synapse.integrations import synapse_node
        from synapse.integrations.langgraph_integration import SynapseConflict
        from synapse.messages import Conflict, ConflictingIntention

        fake_agent._next_conflicts = [
            Conflict(
                intention_id="01HQ" + "0" * 22,
                conflicting_intentions=[
                    ConflictingIntention(
                        intention_id="01HQ" + "0" * 22,
                        agent_id="other",
                        scope=["x.y:w"],
                    )
                ],
                kind="scope_overlap",
            )
        ]

        @synapse_node(
            agent_id="a1", scope=["x.y:w"], expected_outcome="t",
            session_id="s1", blocking=True, gate_ms=10,
        )
        async def node(state: dict) -> dict:
            return state

        with pytest.raises(SynapseConflict):
            await node({})
        # No resolution emitted because we never ran the body
        assert len(fake_agent.resolutions) == 0

    @pytest.mark.asyncio
    async def test_sync_function_wraps_correctly(self, fake_agent):
        from synapse.integrations import synapse_node

        @synapse_node(
            agent_id="a1", scope=["x.y:w"], expected_outcome="t",
            session_id="s1", blocking=False,
        )
        def sync_node(state: dict) -> dict:
            return {**state, "sync": True}

        result = await sync_node({"input": 1})
        assert result == {"input": 1, "sync": True}
        assert len(fake_agent.resolutions) == 1


class TestCrewAIIntegration:
    @pytest.mark.asyncio
    async def test_wraps_callable_with_intention_resolution(self, fake_agent):
        from synapse.integrations import synapse_task

        async def do_work(arg: str) -> str:
            return f"did {arg}"

        wrapped = synapse_task(
            agent_id="a1", scope=["x.y:w"], expected_outcome="t",
            session_id="s1", blocking=False,
        )(do_work)

        result = await wrapped("thing")
        assert result == "did thing"
        assert len(fake_agent.intentions) == 1
        assert len(fake_agent.resolutions) == 1
        assert fake_agent.resolutions[0]["outcome"] == "success"

    @pytest.mark.asyncio
    async def test_wraps_task_object_via_execute_async(self, fake_agent):
        from synapse.integrations import synapse_task

        # Fake CrewAI Task with execute_async + execute_sync
        class FakeTask:
            description = "fake task"
            ran = False

            async def execute_async(self, *a, **kw):
                self.ran = True
                return "task-output"

            def execute_sync(self, *a, **kw):
                self.ran = True
                return "task-output-sync"

        task = FakeTask()
        wrapped = synapse_task(
            agent_id="a1", scope=["x.y:w"], expected_outcome="t",
            session_id="s1", blocking=False,
        )(task)
        result = await wrapped.execute_async()
        assert result == "task-output"
        assert task.ran is True
        assert len(fake_agent.intentions) == 1

    @pytest.mark.asyncio
    async def test_callable_failure_emits_failure_resolution(self, fake_agent):
        from synapse.integrations import synapse_task

        async def boom() -> None:
            raise RuntimeError("kaboom")

        wrapped = synapse_task(
            agent_id="a1", scope=["x.y:w"], expected_outcome="t",
            session_id="s1", blocking=False,
        )(boom)

        with pytest.raises(RuntimeError):
            await wrapped()
        assert fake_agent.resolutions[0]["outcome"] == "failure"
