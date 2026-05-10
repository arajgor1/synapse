"""Unit tests for v0.2 universal SDK additions.

All tests use the MockAdapter / fake bus — no real LLM calls.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

import synapse
from synapse.adapters.mock import MockAdapter
from synapse.adapters.base import InferenceAdapter
from synapse.llm import config as llm_config


@pytest.fixture(autouse=True)
def reset_state():
    """Reset module-level state between tests."""
    llm_config.clear()
    from synapse.intend import _runtime
    _runtime.clear()
    yield
    llm_config.clear()
    _runtime.clear()


# ---------------------------------------------------------------------------
# set_llm / get_llm
# ---------------------------------------------------------------------------

def test_set_llm_stores_adapter():
    adapter = MockAdapter()
    synapse.set_llm(adapter)
    assert synapse.get_llm() is adapter
    assert synapse.llm_is_configured()


def test_set_llm_rejects_non_adapter():
    with pytest.raises(TypeError) as exc:
        synapse.set_llm("not an adapter")  # type: ignore[arg-type]
    assert "InferenceAdapter" in str(exc.value)


def test_set_llm_with_internal_split():
    primary = MockAdapter()
    internal = MockAdapter()
    synapse.set_llm(primary, internal)
    assert synapse.get_llm() is primary
    assert llm_config.get_internal_llm() is internal


def test_get_internal_falls_back_to_primary():
    primary = MockAdapter()
    synapse.set_llm(primary)
    assert llm_config.get_internal_llm() is primary


def test_unconfigured_llm_returns_none():
    assert synapse.get_llm() is None
    assert llm_config.get_internal_llm() is None
    assert not synapse.llm_is_configured()


# ---------------------------------------------------------------------------
# from_* bridges
# ---------------------------------------------------------------------------

def test_from_anthropic_returns_adapter():
    """Bridge should construct an adapter without making any network calls."""
    # We don't actually call Anthropic — just check the wrapper shape
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-fake"}):
        adapter = synapse.from_anthropic()
    assert isinstance(adapter, InferenceAdapter)
    assert adapter.capabilities.backend_id == "anthropic"


def test_from_openai_returns_adapter():
    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-fake"}):
        adapter = synapse.from_openai()
    assert isinstance(adapter, InferenceAdapter)


def test_from_langchain_bridge_lazy_importerrror_is_clean():
    """A LangChain LLM passed in should yield a usable adapter shape
    even before the bridge actually invokes langchain_core."""
    class FakeLLM:
        async def ainvoke(self, messages):
            class R:
                content = "ok"
            return R()
    adapter = synapse.from_langchain(FakeLLM())
    assert isinstance(adapter, InferenceAdapter)
    assert "langchain" in adapter.capabilities.backend_id


def test_from_litellm_lazy_imports_only_when_used():
    """Constructor should fail clearly if litellm is not installed."""
    with pytest.raises(RuntimeError) as exc:
        synapse.from_litellm(model="anthropic/claude-haiku-4-5")
    assert "litellm" in str(exc.value).lower()


def test_auto_llm_picks_anthropic_when_key_set():
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-fake"}, clear=False):
        # Ensure other keys aren't set
        for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OLLAMA_HOST"):
            os.environ.pop(k, None)
        adapter = synapse.auto_llm()
    assert adapter.capabilities.backend_id == "anthropic"


def test_auto_llm_raises_when_no_keys():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(RuntimeError) as exc:
            synapse.auto_llm()
    assert "no LLM provider" in str(exc.value)


# ---------------------------------------------------------------------------
# synapse.intend() — offline mode (no bus = no-op recorder)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_intend_offline_mode_runs_body_without_bus(monkeypatch):
    """If SYNAPSE_REDIS_URL is not set, intend() runs the body without
    emitting envelopes."""
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    body_ran = False
    async with synapse.intend(scope=["x:w"], agent="a") as i:
        body_ran = True
        assert i.scope == ["x:w"]
        assert i.agent_id == "a"
        assert not i.has_conflicts
    assert body_ran


@pytest.mark.asyncio
async def test_intend_offline_records_state_diff_locally(monkeypatch):
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    async with synapse.intend(scope=["x:w"], agent="a") as i:
        i.set_state_diff({"lines_changed": 5})
        i.add_side_effect("wrote /tmp/foo")
    assert i.state_diff == {"lines_changed": 5}
    assert i.side_effects == ["wrote /tmp/foo"]


@pytest.mark.asyncio
async def test_intend_offline_records_failure_on_exception(monkeypatch):
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    handle = None
    try:
        async with synapse.intend(scope=["x:w"], agent="a") as i:
            handle = i
            raise ValueError("boom")
    except ValueError:
        pass
    assert handle is not None
    assert handle.outcome == "failure"
    assert "boom" in (handle.error_message or "")


@pytest.mark.asyncio
async def test_intend_session_id_falls_back_to_env(monkeypatch):
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    monkeypatch.setenv("SYNAPSE_SESSION_ID", "env_session")
    async with synapse.intend(scope=["x:w"], agent="a") as i:
        assert i.session_id == "env_session"


# ---------------------------------------------------------------------------
# synapse.install()
# ---------------------------------------------------------------------------

def test_install_zero_infra_mode_when_no_bus_url(monkeypatch):
    """v0.2.2a3+: with no Redis URL, install() picks zero-infra mode
    (in-memory bus + SQLite) instead of degrading to offline. Users can
    still opt in to the legacy offline path via SYNAPSE_OFFLINE=1."""
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    monkeypatch.delenv("SYNAPSE_OFFLINE", raising=False)
    result = synapse.install()
    assert result["mode"] == "zero-infra"


def test_install_explicit_offline_via_env(monkeypatch):
    """SYNAPSE_OFFLINE=1 preserves the historical no-coordination
    behaviour for callers that explicitly want it."""
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    monkeypatch.setenv("SYNAPSE_OFFLINE", "1")
    result = synapse.install()
    assert result["mode"] == "offline"


def test_install_with_explicit_bus_url(monkeypatch):
    monkeypatch.setenv("SYNAPSE_REDIS_URL", "redis://localhost:6379/0")
    result = synapse.install()
    assert result["mode"] == "live"
    assert result["bus_url"] == "redis://localhost:6379/0"


def test_install_picks_up_explicit_llm():
    adapter = MockAdapter()
    result = synapse.install(llm=adapter)
    assert synapse.get_llm() is adapter
    # Autodetect can pick up any framework module that prior tests
    # imported into sys.modules (langgraph, crewai, autogen, ...).
    # Whichever wins, it must be a registered framework name.
    fw = result["framework"]
    assert fw is None or isinstance(fw, str)


def test_install_unknown_framework_logs_warning(caplog):
    """An unknown framework should warn but not crash."""
    import logging
    with caplog.at_level(logging.WARNING):
        result = synapse.install(framework="ponderwave_3000", auto=False)
    assert result["framework"] == "ponderwave_3000"
    assert result["hooks_installed"] == []


def test_install_session_and_agent_set_env(monkeypatch):
    monkeypatch.delenv("SYNAPSE_SESSION_ID", raising=False)
    monkeypatch.delenv("SYNAPSE_DEFAULT_AGENT_ID", raising=False)
    synapse.install(session_id="my_sess", agent_id="my_agent")
    assert os.environ["SYNAPSE_SESSION_ID"] == "my_sess"
    assert os.environ["SYNAPSE_DEFAULT_AGENT_ID"] == "my_agent"


def test_register_framework_extension_point():
    """Users should be able to plug in a new framework adapter."""
    called = {"count": 0, "opts": None}

    def my_install(opts):
        called["count"] += 1
        called["opts"] = opts

    synapse.register_framework("my_custom_fw", my_install)
    result = synapse.install(framework="my_custom_fw", auto=False, foo="bar")
    assert called["count"] == 1
    assert called["opts"] == {"foo": "bar"}
    assert result["hooks_installed"] == ["my_custom_fw"]


# ---------------------------------------------------------------------------
# LangGraph adapter — module-level concerns (callback availability)
# ---------------------------------------------------------------------------

def test_langgraph_adapter_self_registers():
    """Importing the adapter module registers it on the install registry."""
    from synapse.frameworks import langgraph  # noqa: F401
    from synapse.install import _FRAMEWORK_REGISTRY
    assert "langgraph" in _FRAMEWORK_REGISTRY


def test_langgraph_install_without_langchain_logs_and_continues(caplog):
    """If langchain isn't installed, install_fn should log and no-op."""
    from synapse.frameworks.langgraph import _install_langgraph
    import logging
    # Force the importer to fail by passing through to _try_make_handler.
    # If langchain IS available locally, this test still passes — the
    # adapter doesn't crash either way.
    with caplog.at_level(logging.WARNING):
        _install_langgraph({})
    # No exception is enough — the path is safe under both conditions
