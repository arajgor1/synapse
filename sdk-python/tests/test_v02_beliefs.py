"""Tests for v0.2 Week 5: belief auto-extraction + live divergence detection.

Mock-only — the LLM is a stub that returns canned JSON; the state graph
is mocked via a small in-memory shim.
"""
from __future__ import annotations

from unittest.mock import patch, AsyncMock

import pytest

import synapse
from synapse.adapters.mock import MockAdapter
from synapse.adapters.base import InferenceAdapter
from synapse.messages import BackendCapabilities
from synapse.beliefs.extractor import (
    FactExtraction, _parse_extraction, extract_beliefs_with_llm,
)
from synapse.beliefs.live_detector import (
    LiveDivergenceResult, detect_live_divergence,
)


@pytest.fixture(autouse=True)
def reset():
    from synapse.intend import _runtime
    from synapse.llm.config import clear as clear_llm
    _runtime.clear()
    clear_llm()
    yield
    _runtime.clear()
    clear_llm()


# ---------------------------------------------------------------------------
# Extractor — JSON parsing
# ---------------------------------------------------------------------------

def test_parse_extraction_clean_json():
    text = '[{"key":"revenue_formula","value":"qty * price","confidence":0.95,"evidence":"r = qty*price"}]'
    facts = _parse_extraction(text)
    assert len(facts) == 1
    assert facts[0].key == "revenue_formula"
    assert facts[0].value == "qty * price"
    assert facts[0].confidence == 0.95
    assert "qty*price" in (facts[0].evidence or "")


def test_parse_extraction_strips_markdown_fences():
    text = '```json\n[{"key":"k","value":"v"}]\n```'
    facts = _parse_extraction(text)
    assert len(facts) == 1
    assert facts[0].key == "k"
    assert facts[0].value == "v"


def test_parse_extraction_tolerates_preamble():
    text = "Here are the facts:\n[{\"key\":\"a\",\"value\":1}]\nThanks!"
    facts = _parse_extraction(text)
    assert len(facts) == 1


def test_parse_extraction_caps_at_three_facts():
    text = ("[" + ",".join(f'{{"key":"k{i}","value":{i}}}' for i in range(10)) + "]")
    facts = _parse_extraction(text)
    assert len(facts) == 3


def test_parse_extraction_drops_malformed_entries():
    text = '[{"key":"good","value":"v"},{"missing_key":"x"},{"key":"good2","value":"w"}]'
    facts = _parse_extraction(text)
    assert len(facts) == 2
    assert facts[0].key == "good"
    assert facts[1].key == "good2"


def test_parse_extraction_empty_returns_empty():
    assert _parse_extraction("[]") == []
    assert _parse_extraction("not json at all") == []
    assert _parse_extraction("") == []


def test_parse_extraction_clamps_confidence():
    text = '[{"key":"k","value":"v","confidence":2.5},{"key":"k2","value":"v2","confidence":-1}]'
    facts = _parse_extraction(text)
    assert facts[0].confidence == 1.0
    assert facts[1].confidence == 0.0


# ---------------------------------------------------------------------------
# Extractor — LLM call wiring
# ---------------------------------------------------------------------------

class _StubLLM(InferenceAdapter):
    """Minimal InferenceAdapter that returns a canned generate() response."""

    capabilities = BackendCapabilities(
        backend_id="stub-llm", tier="hosted",
        supports_midstream_inject=False,
        supports_partial_preservation=False,
        prompt_cache_available=False,
        supports_thinking=False,
        multi_tenant_isolation="none",
    )

    def __init__(self, response: str):
        self._response = response

    async def generate(self, messages, *, max_tokens=300, temperature=0.0, **_):
        return self._response

    async def start_stream(self, *a, **k):
        raise NotImplementedError

    def read_tokens(self, h):
        async def _empty():
            if False: yield None
        return _empty()

    async def inject_and_continue(self, h, i, instruction=""):
        raise NotImplementedError

    async def cancel(self, h):
        return ""


@pytest.mark.asyncio
async def test_extract_beliefs_returns_empty_without_llm():
    """No synapse.set_llm() call ⇒ extractor is a no-op."""
    facts = await extract_beliefs_with_llm(
        tool_name="t", tool_args={"a": 1},
        output="some output",
    )
    assert facts == []


@pytest.mark.asyncio
async def test_extract_beliefs_returns_empty_for_blank_output():
    synapse.set_llm(_StubLLM('[{"key":"k","value":"v"}]'))
    facts = await extract_beliefs_with_llm(
        tool_name="t", tool_args={}, output="",
    )
    assert facts == []


@pytest.mark.asyncio
async def test_extract_beliefs_calls_llm_and_parses_response():
    synapse.set_llm(_StubLLM(
        '[{"key":"revenue_formula","value":"qty*price","confidence":0.9}]'
    ))
    facts = await extract_beliefs_with_llm(
        tool_name="write_file",
        tool_args={"path": "x.py"},
        output="def revenue(qty, price): return qty * price",
    )
    assert len(facts) == 1
    assert facts[0].key == "revenue_formula"


@pytest.mark.asyncio
async def test_extract_beliefs_handles_llm_returning_garbage():
    synapse.set_llm(_StubLLM("the LLM forgot to return JSON"))
    facts = await extract_beliefs_with_llm(
        tool_name="t", tool_args={}, output="some output",
    )
    assert facts == []


# ---------------------------------------------------------------------------
# Live divergence detector — pure function over fake AgentBeliefs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_detect_live_divergence_returns_none_without_state():
    """No state graph configured -> no divergence detection."""
    result = await detect_live_divergence(
        session_id="any", just_emitted_key="revenue_formula",
    )
    assert result is None


@pytest.mark.asyncio
async def test_detect_live_divergence_returns_result_when_disagreement_exists():
    """Stub the state pool to return 2 disagreeing rows."""
    from synapse.intend import _runtime

    fake_rows = [
        {"agent_id": "cleaner", "key": "revenue_formula",
         "value": "qty*price", "confidence": 0.9, "source": "observed"},
        {"agent_id": "analyst", "key": "revenue_formula",
         "value": "qty*price*(1-discount)", "confidence": 0.85, "source": "observed"},
    ]

    class FakeState:
        # v0.2.2a3: backend-agnostic belief API. Both real state graphs
        # (Postgres, SQLite) implement these; the fake mirrors them.
        async def beliefs_for_key(self, session_id, key):
            return fake_rows
        async def beliefs_for_session(self, session_id):
            return fake_rows

    _runtime["state"] = FakeState()
    _runtime["mode"] = "live"

    result = await detect_live_divergence(
        session_id="s1", just_emitted_key="revenue_formula",
    )
    assert result is not None
    assert result.key == "revenue_formula"
    assert sorted(result.agents_involved) == ["analyst", "cleaner"]
    assert "qty*price" in str(result.distinct_values)
    assert "qty*price*(1-discount)" in str(result.distinct_values)
    assert result.severity > 0


@pytest.mark.asyncio
async def test_detect_live_divergence_returns_none_when_one_agent():
    """Single agent on a key -> not a divergence."""
    from synapse.intend import _runtime

    one_row = [{
        "agent_id": "solo", "key": "k",
        "value": "v", "confidence": 0.9, "source": "observed",
    }]

    class FakeState:
        async def beliefs_for_key(self, session_id, key):
            return one_row
        async def beliefs_for_session(self, session_id):
            return one_row

    _runtime["state"] = FakeState()
    _runtime["mode"] = "live"

    result = await detect_live_divergence(session_id="s1", just_emitted_key="k")
    assert result is None


@pytest.mark.asyncio
async def test_detect_live_divergence_returns_none_when_agents_agree():
    """Multiple agents, same value -> not a divergence."""
    from synapse.intend import _runtime

    agree_rows = [
        {"agent_id": "a", "key": "k", "value": "v", "confidence": 0.9, "source": "observed"},
        {"agent_id": "b", "key": "k", "value": "v", "confidence": 0.9, "source": "observed"},
    ]

    class FakeState:
        async def beliefs_for_key(self, session_id, key):
            return agree_rows
        async def beliefs_for_session(self, session_id):
            return agree_rows

    _runtime["state"] = FakeState()
    _runtime["mode"] = "live"

    result = await detect_live_divergence(session_id="s1", just_emitted_key="k")
    assert result is None


def test_live_divergence_result_to_dict_round_trips():
    r = LiveDivergenceResult(
        key="k", distinct_values=["a", "b"],
        agents_involved=["alpha", "beta"], severity=0.7,
        rationale="test",
    )
    d = r.to_dict()
    assert d["key"] == "k"
    assert d["distinct_values"] == ["a", "b"]
    assert d["agents_involved"] == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# install() flag plumbing
# ---------------------------------------------------------------------------

def test_install_default_flag_off(monkeypatch):
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    result = synapse.install(auto=False)
    assert result["emit_beliefs_from_tool_results"] is False


def test_install_emit_beliefs_flag_on(monkeypatch):
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    result = synapse.install(emit_beliefs_from_tool_results=True, auto=False)
    assert result["emit_beliefs_from_tool_results"] is True


@pytest.mark.asyncio
async def test_intend_skips_belief_extraction_when_flag_off(monkeypatch):
    """Without emit_beliefs_from_tool_results=True, no LLM call happens
    even if state_diff is rich."""
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)

    extracted = []

    async def _fake_extract(**kw):
        extracted.append(kw)
        return [FactExtraction(key="k", value="v")]

    with patch("synapse.beliefs.extractor.extract_beliefs_with_llm", side_effect=_fake_extract):
        async with synapse.intend(scope=["x:w"], agent="a") as i:
            i.set_state_diff({"content": "important fact: revenue = qty * price"})

    assert extracted == []  # extractor never invoked


# ---------------------------------------------------------------------------
# emit_belief public API smoke
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_emit_belief_offline_returns_none(monkeypatch):
    """SYNAPSE_OFFLINE=1 -> emit_belief is a logging no-op, returns None.

    Pre-v0.2.2a3 this test asserted the same behaviour just via
    'SYNAPSE_REDIS_URL unset'. v0.2.2a3 introduced zero-infra mode
    (in-memory bus + SQLite) so 'no Redis URL' now means 'real
    coordination via SQLite'. The historical no-coordination behaviour
    is preserved behind the explicit SYNAPSE_OFFLINE opt-out.
    """
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    monkeypatch.setenv("SYNAPSE_OFFLINE", "1")
    from synapse.intend import shutdown as _sd
    await _sd()
    try:
        result = await synapse.emit_belief(
            agent="a", session="s1",
            key="k", value="v",
        )
        assert result is None
    finally:
        await _sd()


@pytest.mark.asyncio
async def test_list_divergences_offline_returns_empty(monkeypatch):
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    monkeypatch.setenv("SYNAPSE_OFFLINE", "1")
    from synapse.intend import shutdown as _sd
    await _sd()
    try:
        result = await synapse.list_divergences(session_id="s1")
        assert result == []
    finally:
        await _sd()
