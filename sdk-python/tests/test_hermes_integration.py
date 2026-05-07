"""Tests for the Hermes Agent integration.

These run without Hermes installed — the integration is designed as a
runtime hook that no-ops when Hermes is not present, so we only need to
exercise the wrap_tool_call_for_synapse function.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO_ROOT)

from synapse.integrations.hermes_integration import (
    HermesSynapseConflict,
    SUBAGENT_SPAWN_TOOLS,
    WRITE_OR_EXECUTE_TOOLS,
    _hermes_runtime,
    _scope_from_tool_call,
    install_hermes_synapse_hooks,
    wrap_tool_call_for_synapse,
)


pytestmark = pytest.mark.asyncio


class _FakeAgent:
    def __init__(self, conflicts_to_return=None):
        self.intentions = []
        self.resolutions = []
        self._conflicts = conflicts_to_return or []

    async def emit_intention(self, **kwargs):
        self.intentions.append(kwargs)
        return ("01HQ" + "0" * 22, list(self._conflicts))

    async def emit_resolution(self, **kwargs):
        self.resolutions.append(kwargs)


class TestScopeFromToolCall:
    def test_write_file_scopes_by_path(self) -> None:
        scope = _scope_from_tool_call("write_file", {"path": "src/auth/middleware.py"})
        assert scope == ["repo.fs.src/auth/middleware.py:w"]

    def test_patch_uses_path(self) -> None:
        scope = _scope_from_tool_call("patch", {"path": "src/main.py"})
        assert scope == ["repo.fs.src/main.py:w"]

    def test_terminal_uses_shell_scope(self) -> None:
        scope = _scope_from_tool_call("terminal", {"cmd": "rm -rf /"})
        assert scope == ["repo.shell:w"]

    def test_browser_uses_url_scope(self) -> None:
        scope = _scope_from_tool_call(
            "browser_navigate", {"url": "https://example.com"}
        )
        assert scope[0].startswith("repo.browser.")

    def test_delegate_task_uses_subagent_scope(self) -> None:
        scope = _scope_from_tool_call("delegate_task", {"agent_id": "child_a"})
        assert scope == ["hermes.subagent.child_a:w"]

    def test_unknown_tool_falls_back(self) -> None:
        scope = _scope_from_tool_call("custom_thing", {})
        assert scope == ["hermes.tool.custom_thing:w"]

    def test_path_special_chars_sanitized(self) -> None:
        scope = _scope_from_tool_call("write_file", {"path": "a b@c.py"})
        # spaces and @ get replaced with _
        assert scope[0] == "repo.fs.a_b_c.py:w"


class TestWrapToolCallForSynapse:
    async def test_no_op_when_hooks_not_installed(self, monkeypatch) -> None:
        # Reset runtime
        _hermes_runtime.clear()

        async def inner():
            return "ok"

        result = await wrap_tool_call_for_synapse("write_file", {"path": "x"}, inner)
        assert result == "ok"

    async def test_read_only_tool_skips_intention(self, monkeypatch) -> None:
        agent = _FakeAgent()
        _hermes_runtime["agent"] = agent
        _hermes_runtime["session_id"] = "s"
        _hermes_runtime["gate_ms"] = 5
        _hermes_runtime["fail_on_conflict"] = False

        async def inner():
            return "data"

        result = await wrap_tool_call_for_synapse("read_file", {"path": "x"}, inner)
        assert result == "data"
        assert agent.intentions == []  # read-only -> no INTENTION

    async def test_write_tool_emits_intention_and_resolution(self) -> None:
        agent = _FakeAgent()
        _hermes_runtime["agent"] = agent
        _hermes_runtime["session_id"] = "s"
        _hermes_runtime["gate_ms"] = 5
        _hermes_runtime["fail_on_conflict"] = False

        async def inner():
            return "wrote bytes"

        result = await wrap_tool_call_for_synapse(
            "write_file", {"path": "out.txt"}, inner
        )
        assert result == "wrote bytes"
        assert len(agent.intentions) == 1
        assert agent.intentions[0]["scope"] == ["repo.fs.out.txt:w"]
        assert len(agent.resolutions) == 1
        assert agent.resolutions[0]["outcome"] == "success"

    async def test_failure_emits_failure_resolution(self) -> None:
        agent = _FakeAgent()
        _hermes_runtime["agent"] = agent
        _hermes_runtime["session_id"] = "s"
        _hermes_runtime["gate_ms"] = 5
        _hermes_runtime["fail_on_conflict"] = False

        async def inner():
            raise RuntimeError("disk full")

        with pytest.raises(RuntimeError, match="disk full"):
            await wrap_tool_call_for_synapse(
                "execute_code", {"code": "1/0"}, inner,
            )
        assert len(agent.resolutions) == 1
        assert agent.resolutions[0]["outcome"] == "failure"
        assert "disk full" in agent.resolutions[0]["state_diff"]["error"]

    async def test_conflict_with_fail_on_conflict_raises(self) -> None:
        # Simulate a conflict from the gate
        from synapse.messages import Conflict, ConflictingIntention

        agent = _FakeAgent(
            conflicts_to_return=[
                Conflict(
                    intention_id="01HQ" + "0" * 22,
                    conflicting_intentions=[
                        ConflictingIntention(
                            intention_id="01HQ" + "0" * 22,
                            agent_id="other",
                            scope=["repo.fs.x:w"],
                        )
                    ],
                    kind="scope_overlap",
                    overlapping_scopes=["repo.fs.x:w"],
                )
            ]
        )
        _hermes_runtime["agent"] = agent
        _hermes_runtime["session_id"] = "s"
        _hermes_runtime["gate_ms"] = 5
        _hermes_runtime["fail_on_conflict"] = True

        async def inner():
            return "would-have-been-written"

        with pytest.raises(HermesSynapseConflict):
            await wrap_tool_call_for_synapse(
                "write_file", {"path": "x"}, inner,
            )
        # No resolution because we never reached inner_call
        assert len(agent.resolutions) == 0


class TestKnownToolSets:
    def test_write_or_execute_includes_canonical_hermes_tools(self) -> None:
        # Sample canonical hermes tools should be flagged write/execute
        for t in (
            "write_file", "patch", "terminal", "execute_code",
            "delegate_task", "browser_click",
        ):
            assert t in WRITE_OR_EXECUTE_TOOLS

    def test_read_tools_not_in_write_set(self) -> None:
        for t in ("read_file", "search_files", "web_search", "skill_view"):
            assert t not in WRITE_OR_EXECUTE_TOOLS

    def test_subagent_spawn_subset_of_writes(self) -> None:
        assert SUBAGENT_SPAWN_TOOLS.issubset(WRITE_OR_EXECUTE_TOOLS)
