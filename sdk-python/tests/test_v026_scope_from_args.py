"""Regression test for v0.2.6 scope_from_args / scope_from_task config
on crewai + pydantic_ai adapters.

Phase 6 + 7b findings: by default crewai uses per-task UUID scopes and
pydantic_ai uses per-tool-name scopes — neither auto-detects file-level
contention. The v0.2.6 fix exposes a configurable hook so operators
can opt into file-path-aware (or any custom) scope semantics.
"""
from __future__ import annotations

import os
import pytest


# ============================================================================
# CREWAI
# ============================================================================
pytest.importorskip("crewai")


def test_crewai_scope_from_task_hook_registered():
    """User-supplied scope_from_task is captured and used in _scope_from_task."""
    import synapse
    import synapse.frameworks.crewai as ca

    # Custom hook that scopes by a task's role
    def by_role(task):
        agent = getattr(task, "agent", None)
        if agent is not None:
            role = getattr(agent, "role", None)
            if role:
                return [f"role.{role.lower().replace(' ', '_')}:w"]
        return None

    synapse.install(framework="crewai", scope_from_task=by_role)

    # Confirm config captured
    assert ca._CONFIG.get("scope_from_task") is by_role

    # Build a Task with a mock agent role and verify scope reflects the hook
    class FakeAgent:
        role = "Backend Engineer"
    class FakeTask:
        agent = FakeAgent()
        description = "ignore me"
        expected_output = "ignore me"
        id = "task-abc-123"

    scope = ca._scope_from_task(FakeTask())
    assert scope == ["role.backend_engineer:w"], (
        f"hook scope not used; got {scope}"
    )


def test_crewai_scope_hook_falls_back_on_None():
    """If the hook returns None, the default heuristic kicks in."""
    import synapse
    import synapse.frameworks.crewai as ca

    # Reset and re-install with a hook that returns None
    ca._CONFIG.clear()
    synapse.install(framework="crewai", scope_from_task=lambda t: None)

    class FakeTask:
        description = "write to app/models.py please"
        expected_output = ""
        agent = None
        id = "tabc"
    scope = ca._scope_from_task(FakeTask())
    # File-path heuristic should detect "app/models.py"
    assert scope == ["repo.fs.app/models.py:w"], f"fallback didn't fire: {scope}"


def test_crewai_scope_hook_falls_back_on_exception():
    """If the hook raises, log a warning and fall back to default heuristic."""
    import synapse
    import synapse.frameworks.crewai as ca

    ca._CONFIG.clear()
    def buggy(task):
        raise ValueError("oops")
    synapse.install(framework="crewai", scope_from_task=buggy)

    class FakeTask:
        description = "no path here"
        expected_output = ""
        agent = None
        id = "tabc"
    scope = ca._scope_from_task(FakeTask())
    # Should fall back to crewai.task.<id>:w
    assert scope == ["crewai.task.tabc:w"], f"didn't fall back: {scope}"


# ============================================================================
# PYDANTIC_AI
# ============================================================================
pytest.importorskip("pydantic_ai")


def test_pydantic_ai_scope_from_args_hook_registered():
    """User-supplied scope_from_args is captured + used by _scope_from_call."""
    import synapse
    import synapse.frameworks.pydantic_ai as pa

    # Custom hook: scope by the explicit file path arg
    def by_file(tool_name, args):
        p = args.get("file_path") or args.get("path")
        return [f"repo.fs.{p}:w"] if p else None

    pa._CONFIG.clear()
    synapse.install(framework="pydantic_ai", scope_from_args=by_file)
    assert pa._CONFIG.get("scope_from_args") is by_file

    scope = pa._scope_from_call("write_file", {"file_path": "src/app.py", "content": "..."})
    assert scope == ["repo.fs.src/app.py:w"], f"hook scope not used: {scope}"


def test_pydantic_ai_scope_hook_falls_back_on_None():
    """If the user hook returns None, default infer_scope (or per-tool-name)
    fallback fires."""
    import synapse
    import synapse.frameworks.pydantic_ai as pa

    pa._CONFIG.clear()
    synapse.install(framework="pydantic_ai", scope_from_args=lambda n, a: None)

    # No file path in args → default falls back to per-tool-name scope
    scope = pa._scope_from_call("my_custom_tool", {"content": "hi"})
    assert scope == ["pydantic_ai.tool.my_custom_tool:w"], (
        f"fallback didn't fire: {scope}"
    )


def test_pydantic_ai_scope_hook_falls_back_on_exception():
    """Exception in hook → default heuristic."""
    import synapse
    import synapse.frameworks.pydantic_ai as pa

    pa._CONFIG.clear()
    def buggy(n, a):
        raise RuntimeError("kaboom")
    synapse.install(framework="pydantic_ai", scope_from_args=buggy)

    scope = pa._scope_from_call("my_tool", {"x": 1})
    assert scope == ["pydantic_ai.tool.my_tool:w"]
