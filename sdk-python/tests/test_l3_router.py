"""L3 router unit tests — JSON parsing, candidate filter, threshold logic.

No live LLM or bus calls.
"""

from __future__ import annotations

import os
import sys
import time

import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO_ROOT)

from runtime.router.l3_semantic import L3Stats


class TestL3Stats:
    def test_default_threshold(self) -> None:
        s = L3Stats()
        assert 0.5 <= s.threshold <= 1.0
        assert s.messages_seen == 0
        assert s.messages_routed == 0


class TestL3Threshold:
    """The adjust_threshold logic on a fake router. We instantiate a partial
    L3SemanticRouter via a small stub since the real one needs a backend.
    """

    def setup_method(self) -> None:
        # Build a minimal stub
        from runtime.router.l3_semantic import L3SemanticRouter

        class _StubBackend:
            class capabilities:
                backend_id = "stub"
                tier = "hosted"
                supports_midstream_inject = False
                model_id = None

        # Skip __init__ to avoid bus/state requirements
        self.router = L3SemanticRouter.__new__(L3SemanticRouter)
        self.router.stats = L3Stats(threshold=0.7)

    def test_high_cost_raises_threshold(self) -> None:
        before = self.router.stats.threshold
        self.router.adjust_threshold(0.005)  # 5x target
        assert self.router.stats.threshold > before

    def test_low_cost_lowers_threshold(self) -> None:
        # Start higher
        self.router.stats.threshold = 0.85
        before = self.router.stats.threshold
        self.router.adjust_threshold(0.0001)  # below half target
        assert self.router.stats.threshold < before

    def test_threshold_capped_at_0_95(self) -> None:
        self.router.stats.threshold = 0.95
        self.router.adjust_threshold(1.0)
        assert self.router.stats.threshold <= 0.95

    def test_threshold_floored_at_0_5(self) -> None:
        self.router.stats.threshold = 0.5
        self.router.adjust_threshold(0.0)
        assert self.router.stats.threshold >= 0.5


class TestOpenAIAdapter:
    def test_raises_without_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        try:
            from synapse.adapters.hosted import OpenAIAdapter
        except ImportError:
            pytest.skip("openai package not installed")
        from synapse.adapters.base import BackendUnavailable
        with pytest.raises(BackendUnavailable, match="OPENAI_API_KEY"):
            OpenAIAdapter()

    def test_reasoning_model_capability_flagged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
        try:
            from synapse.adapters.hosted import OpenAIAdapter
        except ImportError:
            pytest.skip("openai package not installed")
        adapter = OpenAIAdapter(model="o3")
        caps = adapter.capabilities
        assert caps.is_reasoning_model is True
        assert caps.supports_midstream_inject is False

    def test_non_reasoning_model_supports_midstream(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
        try:
            from synapse.adapters.hosted import OpenAIAdapter
        except ImportError:
            pytest.skip("openai package not installed")
        adapter = OpenAIAdapter(model="gpt-4o-mini")
        caps = adapter.capabilities
        assert caps.is_reasoning_model is False
        assert caps.supports_midstream_inject is True

    def test_estimate_cost(self) -> None:
        try:
            from synapse.adapters.hosted.openai_adapter import OpenAIAdapter
        except ImportError:
            pytest.skip("openai package not installed")
        cost = OpenAIAdapter.estimate_cost_usd("gpt-4o-mini", 1_000_000, 500_000)
        # 0.15 input + 0.30 output = 0.45
        assert abs(cost - 0.45) < 0.01
