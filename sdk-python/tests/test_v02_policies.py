"""Tests for v0.2 Week 4: MergePolicy + critical_scopes.

All mock-only — no real LLM calls. The auto_merge policy is exercised
with a stub adapter that returns a fixed merge result so we can assert
behavior without network.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

import synapse
from synapse.adapters.mock import MockAdapter
from synapse.adapters.base import InferenceAdapter
from synapse.messages import BackendCapabilities
from synapse.policies import (
    AbortPolicy,
    AutoMergePolicy,
    MergeAction,
    MergeDecision,
    MergePolicy,
    NoOpPolicy,
    RedirectPolicy,
    SynapseConflict,
    WaitPolicy,
    critical_scope_match,
    normalize_critical_scopes,
    resolve_policy,
)
from synapse.intend import IntentionHandle


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
# critical_scope_match — glob matcher
# ---------------------------------------------------------------------------

def test_critical_scope_matches_exact():
    assert critical_scope_match(["billing.charge:w"], ["billing.charge"]) == "billing.charge"


def test_critical_scope_matches_glob():
    m = critical_scope_match(["billing.charge:w"], ["billing.*"])
    assert m == "billing.*"


def test_critical_scope_no_match():
    assert critical_scope_match(["repo.fs.foo.py:w"], ["billing.*"]) is None


def test_critical_scope_strips_modifier_on_pattern_too():
    """Patterns with their own :w modifier still match read-only scopes
    (we strip both sides)."""
    assert critical_scope_match(["billing.charge:r"], ["billing.charge:w"]) == "billing.charge:w"


def test_normalize_critical_scopes_strips_empties():
    assert normalize_critical_scopes(["", "  ", "billing.*", None]) == ["billing.*"]
    assert normalize_critical_scopes(None) == []


# ---------------------------------------------------------------------------
# resolve_policy — coerces names/instances/None
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,cls", [
    ("redirect", RedirectPolicy),
    ("wait", WaitPolicy),
    ("abort", AbortPolicy),
    ("auto_merge", AutoMergePolicy),
    ("automerge", AutoMergePolicy),
    ("no_op", NoOpPolicy),
])
def test_resolve_policy_by_name(name, cls):
    pol = resolve_policy(name)
    assert isinstance(pol, cls)


def test_resolve_policy_passes_through_instances():
    abort = AbortPolicy()
    assert resolve_policy(abort) is abort


def test_resolve_policy_returns_none_for_none():
    assert resolve_policy(None) is None


def test_resolve_policy_unknown_string_returns_none():
    assert resolve_policy("ponderwave") is None


def test_resolve_policy_rejects_garbage_type():
    with pytest.raises(TypeError):
        resolve_policy(42)


# ---------------------------------------------------------------------------
# Built-in policy behaviors (offline / no LLM)
# ---------------------------------------------------------------------------

def _handle(scope=None, agent="a", session="s") -> IntentionHandle:
    return IntentionHandle(
        intention_id="i", scope=scope or ["x:w"], agent_id=agent, session_id=session,
    )


@pytest.mark.asyncio
async def test_no_op_proceeds():
    a = await NoOpPolicy().resolve(_handle(), conflicts=[object(), object()])
    assert a.decision == MergeDecision.PROCEED


@pytest.mark.asyncio
async def test_abort_returns_abort():
    a = await AbortPolicy().resolve(_handle(), conflicts=[object()])
    assert a.decision == MergeDecision.ABORT
    assert "Abort" in a.rationale


@pytest.mark.asyncio
async def test_wait_returns_wait_with_timeout():
    a = await WaitPolicy(timeout_ms=1234).resolve(_handle(), conflicts=[object()])
    assert a.decision == MergeDecision.WAIT
    assert a.wait_timeout_ms == 1234


@pytest.mark.asyncio
async def test_redirect_includes_other_agents_in_rationale():
    class FakeCI:
        def __init__(self, aid):
            self.agent_id = aid

    class FakeConflict:
        conflicting_intentions = [FakeCI("alice"), FakeCI("bob")]
        suggested_resolution = "pivot"

    a = await RedirectPolicy().resolve(_handle(), conflicts=[FakeConflict()])
    assert a.decision == MergeDecision.PROCEED
    assert "alice" in a.rationale
    assert "bob" in a.rationale


@pytest.mark.asyncio
async def test_auto_merge_falls_back_to_proceed_without_llm():
    """No synapse.set_llm() — auto_merge must fall back to PROCEED, never crash."""
    a = await AutoMergePolicy().resolve(
        _handle(), conflicts=[object()],
        proposed_action={"path": "x.py", "content": "hello"},
    )
    assert a.decision == MergeDecision.PROCEED
    assert "no LLM" in a.rationale.lower() or "skip" in a.rationale.lower()


@pytest.mark.asyncio
async def test_auto_merge_falls_back_without_proposed_action():
    """auto_merge requires proposed_action[content_key]; without it,
    falls back gracefully."""
    synapse.set_llm(MockAdapter())
    a = await AutoMergePolicy().resolve(
        _handle(), conflicts=[object()], proposed_action=None,
    )
    assert a.decision == MergeDecision.PROCEED


@pytest.mark.asyncio
async def test_auto_merge_calls_llm_and_returns_merged():
    """When LLM, proposed_action, and prior_content all present, the
    policy returns MERGED with merged_action filled in."""

    class StubLLM(InferenceAdapter):
        capabilities = BackendCapabilities(
            backend_id="stub", tier="hosted",
            supports_midstream_inject=False,
            supports_partial_preservation=False,
            prompt_cache_available=False,
            supports_thinking=False,
            multi_tenant_isolation="none",
        )

        async def generate(self, messages, *, max_tokens=1500, temperature=0.0, **_):
            return "MERGED_CONTENT"

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

    synapse.set_llm(StubLLM())

    # Patch out the prior-content lookup so the test doesn't need a bus
    async def fake_priors(handle, conflicts, key):
        return [{"agent_id": "alice", "intention_id": "i_alice", "content": "ALICE_CONTENT"}]

    with patch("synapse.policies.builtin._fetch_all_prior_content", side_effect=fake_priors):
        a = await AutoMergePolicy().resolve(
            _handle(),
            conflicts=[object()],
            proposed_action={"path": "x.py", "content": "BOB_CONTENT"},
        )

    assert a.decision == MergeDecision.MERGED
    assert a.merged_action == {"path": "x.py", "content": "MERGED_CONTENT"}
    assert "alice" in a.rationale.lower()


# ---------------------------------------------------------------------------
# synapse.MergePolicy.* class-level singletons
# ---------------------------------------------------------------------------

def test_class_level_singletons():
    assert synapse.MergePolicy.redirect.name == "redirect"
    assert synapse.MergePolicy.wait.name == "wait"
    assert synapse.MergePolicy.abort.name == "abort"
    assert synapse.MergePolicy.auto_merge.name == "auto_merge"
    assert synapse.MergePolicy.no_op.name == "no_op"


# ---------------------------------------------------------------------------
# Integration: synapse.intend() respects policies
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_intend_offline_with_abort_policy_doesnt_run_body(monkeypatch):
    """Without a bus configured, no conflicts can fire — abort policy
    is a no-op. The body still runs."""
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    body_ran = False
    async with synapse.intend(
        scope=["x:w"], agent="a",
        merge_policy=synapse.MergePolicy.abort,
    ) as i:
        body_ran = True
    assert body_ran  # offline mode = no conflicts = abort never triggers


@pytest.mark.asyncio
async def test_intend_critical_scopes_passed_offline_no_op(monkeypatch):
    """critical_scopes only fire when conflicts exist. In offline mode,
    they should be a no-op."""
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    async with synapse.intend(
        scope=["billing.charge:w"], agent="a",
        critical_scopes=["billing.*"],
    ) as i:
        pass


@pytest.mark.asyncio
async def test_intend_with_explicit_proposed_action_records_it(monkeypatch):
    """proposed_action is accepted (mostly used by auto_merge) without
    breaking the offline path."""
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    async with synapse.intend(
        scope=["x:w"], agent="a",
        proposed_action={"path": "y.py", "content": "code"},
    ) as i:
        assert not i.has_conflicts
        assert i.merged_action is None  # auto_merge wasn't configured


# ---------------------------------------------------------------------------
# install() merge_policy + critical_scopes plumbing
# ---------------------------------------------------------------------------

def test_install_stores_merge_policy_default(monkeypatch):
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    result = synapse.install(merge_policy=synapse.MergePolicy.redirect, auto=False)
    assert result["merge_policy"] == "redirect"


def test_install_stores_critical_scopes(monkeypatch):
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    result = synapse.install(
        critical_scopes=["billing.*", "prod.deploy.*"], auto=False,
    )
    assert result["critical_scopes"] == ["billing.*", "prod.deploy.*"]


def test_install_accepts_string_policy_name(monkeypatch):
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    result = synapse.install(merge_policy="abort", auto=False)
    assert result["merge_policy"] == "abort"


def test_install_unknown_policy_string_falls_through(monkeypatch):
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    result = synapse.install(merge_policy="ponderwave", auto=False)
    # Unknown name -> resolve_policy returns None -> stored as None
    assert result["merge_policy"] is None
