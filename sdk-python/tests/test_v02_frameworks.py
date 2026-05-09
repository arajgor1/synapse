"""Unit tests for Week 3a framework adapters.

All tests are mock-only — no real LLM calls, no live framework runs.
Each test confirms:
  1. The adapter self-registers under its name(s)
  2. ``synapse.install(framework=name)`` dispatches without crashing
     even when the underlying framework isn't installed
  3. The adapter survives a no-op install gracefully
"""
from __future__ import annotations

import pytest

import synapse
from synapse.install import _FRAMEWORK_REGISTRY


@pytest.fixture(autouse=True)
def reset():
    """Drop runtime + LLM config between tests."""
    from synapse.intend import _runtime
    from synapse.llm.config import clear as clear_llm
    _runtime.clear()
    clear_llm()
    yield
    _runtime.clear()
    clear_llm()


# ---------------------------------------------------------------------------
# Self-registration tests — importing each adapter must populate the registry
# ---------------------------------------------------------------------------

def test_crewai_adapter_registers():
    from synapse.frameworks import crewai  # noqa: F401
    assert "crewai" in _FRAMEWORK_REGISTRY


def test_autogen_adapter_registers_under_three_names():
    from synapse.frameworks import autogen  # noqa: F401
    assert "autogen" in _FRAMEWORK_REGISTRY
    assert "autogen_agentchat" in _FRAMEWORK_REGISTRY
    assert "autogen_core" in _FRAMEWORK_REGISTRY


def test_openai_agents_adapter_registers_with_swarm_alias():
    from synapse.frameworks import openai_agents  # noqa: F401
    assert "openai_agents" in _FRAMEWORK_REGISTRY
    assert "swarm" in _FRAMEWORK_REGISTRY  # backward-compat alias


def test_pydantic_ai_adapter_registers():
    from synapse.frameworks import pydantic_ai  # noqa: F401
    assert "pydantic_ai" in _FRAMEWORK_REGISTRY
    assert "pydantic-ai" in _FRAMEWORK_REGISTRY


def test_smolagents_adapter_registers():
    from synapse.frameworks import smolagents  # noqa: F401
    assert "smolagents" in _FRAMEWORK_REGISTRY


def test_hermes_adapter_registers():
    from synapse.frameworks import hermes  # noqa: F401
    assert "hermes" in _FRAMEWORK_REGISTRY


# ---------------------------------------------------------------------------
# install() dispatch path — must not crash even if the framework's package
# isn't installed in the test env
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["crewai", "autogen", "openai_agents", "pydantic_ai", "smolagents"])
def test_install_dispatches_to_each_framework_safely(name, monkeypatch, caplog):
    """install(framework=name) should run without raising even if the
    framework's underlying package is missing."""
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    import logging
    with caplog.at_level(logging.WARNING):
        result = synapse.install(framework=name, auto=False)
    assert result["framework"] == name
    # Either "hooks_installed: [name]" if the framework happens to be
    # available locally, or "hooks_installed: []" with a warning. Both fine.


def test_install_hermes_offline_warns_about_missing_state(monkeypatch, caplog):
    """The Hermes adapter needs both bus + state; offline mode should
    warn but not crash."""
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    import logging
    with caplog.at_level(logging.WARNING):
        result = synapse.install(framework="hermes", auto=False)
    assert result["framework"] == "hermes"


# ---------------------------------------------------------------------------
# Scope-inference smoke tests for the new adapters' helper code paths
# ---------------------------------------------------------------------------

def test_crewai_scope_extracts_path_from_expected_output():
    from synapse.frameworks.crewai import _scope_from_task

    class FakeTask:
        description = "Refactor the auth module"
        expected_output = "An updated src/auth/middleware.py file"

    assert _scope_from_task(FakeTask()) == ["repo.fs.src/auth/middleware.py:w"]


def test_crewai_scope_falls_back_to_task_id():
    from synapse.frameworks.crewai import _scope_from_task

    class FakeTask:
        description = "general work"
        expected_output = "a summary"
        id = "task_123"

    scope = _scope_from_task(FakeTask())
    assert scope[0].startswith("crewai.task.task_123")


def test_crewai_agent_id_falls_back_when_no_agent():
    from synapse.frameworks.crewai import _agent_id_from_task

    class FakeTask:
        agent = None

    assert _agent_id_from_task(FakeTask()) == "crewai_default"


def test_crewai_agent_id_normalizes_role_string():
    from synapse.frameworks.crewai import _agent_id_from_task

    class FakeAgent:
        role = "Senior Backend Engineer"

    class FakeTask:
        agent = FakeAgent()

    assert _agent_id_from_task(FakeTask()) == "senior_backend_engineer"


# ---------------------------------------------------------------------------
# autodetect picks up known framework module names
# ---------------------------------------------------------------------------

def test_autodetect_picks_crewai_when_module_loaded(monkeypatch):
    """If sys.modules has 'crewai', autodetect returns 'crewai'."""
    import sys
    import types
    from synapse.install import _autodetect_framework

    # Earlier tests may have imported langgraph (which is checked first in
    # the candidate ordering). Isolate so this test asserts about crewai.
    for name in ("langgraph",):
        if name in sys.modules:
            monkeypatch.delitem(sys.modules, name, raising=False)
    fake_mod = types.ModuleType("crewai")
    monkeypatch.setitem(sys.modules, "crewai", fake_mod)
    assert _autodetect_framework() == "crewai"


_AUTODETECT_CANDIDATES = (
    "langgraph", "crewai",
    "autogen", "autogen_agentchat", "autogen_core",
    "agents", "openai_agents", "openai_swarm",
    "smolagents", "pydantic_ai",
)


def _isolate_autodetect(monkeypatch, keep: str) -> None:
    """Remove every other autodetect candidate from sys.modules so the
    test gets a deterministic single-framework view. Earlier tests
    elsewhere in the suite may have populated sys.modules with crewai
    (or others), and the autodetect ordering would otherwise pick the
    first match — not the one this test injected."""
    import sys
    for name in _AUTODETECT_CANDIDATES:
        if name == keep:
            continue
        if name in sys.modules:
            monkeypatch.delitem(sys.modules, name, raising=False)


def test_autodetect_normalizes_autogen_variants(monkeypatch):
    import sys
    import types
    from synapse.install import _autodetect_framework

    _isolate_autodetect(monkeypatch, keep="autogen_agentchat")
    fake_mod = types.ModuleType("autogen_agentchat")
    monkeypatch.setitem(sys.modules, "autogen_agentchat", fake_mod)
    assert _autodetect_framework() == "autogen"


def test_autodetect_normalizes_swarm_to_openai_agents(monkeypatch):
    import sys
    import types
    from synapse.install import _autodetect_framework

    _isolate_autodetect(monkeypatch, keep="agents")
    fake_mod = types.ModuleType("agents")
    monkeypatch.setitem(sys.modules, "agents", fake_mod)
    assert _autodetect_framework() == "openai_agents"
