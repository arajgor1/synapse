"""Tests for hosted adapters — capability surface, message prep, error handling.

Does NOT make any real API calls. Live integration is exercised by
examples/two_agents_with_real_llm.py.
"""

from __future__ import annotations

import os
import pytest

from synapse.adapters.base import BackendUnavailable


class TestAnthropicAdapter:
    def test_raises_without_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from synapse.adapters.hosted import AnthropicAdapter
        with pytest.raises(BackendUnavailable, match="ANTHROPIC_API_KEY"):
            AnthropicAdapter()

    def test_capabilities_correct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
        from synapse.adapters.hosted import AnthropicAdapter
        adapter = AnthropicAdapter(model="claude-haiku-4-5-20251001")
        caps = adapter.capabilities
        assert caps.backend_id == "anthropic"
        assert caps.tier == "hosted"
        assert caps.supports_midstream_inject is True
        assert caps.supports_partial_preservation is True
        assert caps.prompt_cache_available is True
        assert 1.0 < caps.avg_overhead_per_signal < 2.0
        assert caps.model_id == "claude-haiku-4-5-20251001"

    def test_system_message_extracted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
        from synapse.adapters.hosted import AnthropicAdapter
        adapter = AnthropicAdapter()
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "hi"},
        ]
        out, system = adapter._prepare_messages(messages)
        assert system == "You are helpful."
        assert len(out) == 1
        assert out[0]["role"] == "user"

    def test_estimate_cost_zero_for_unknown_model(self) -> None:
        from synapse.adapters.hosted.anthropic_adapter import AnthropicAdapter
        assert AnthropicAdapter.estimate_cost_usd("unknown-model", 100, 50) == 0.0

    def test_estimate_cost_with_cache(self) -> None:
        from synapse.adapters.hosted.anthropic_adapter import AnthropicAdapter
        cost = AnthropicAdapter.estimate_cost_usd(
            "claude-haiku-4-5-20251001",
            tokens_in=1000,
            tokens_out=500,
            tokens_cached=800,
        )
        assert cost > 0
        # Cached tokens should reduce cost vs all uncached
        cost_no_cache = AnthropicAdapter.estimate_cost_usd(
            "claude-haiku-4-5-20251001",
            tokens_in=1000,
            tokens_out=500,
            tokens_cached=0,
        )
        assert cost < cost_no_cache


class TestGeminiAdapter:
    def test_raises_without_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        from synapse.adapters.hosted import GeminiAdapter
        with pytest.raises(BackendUnavailable, match="GOOGLE_API_KEY"):
            GeminiAdapter()

    def test_capabilities_correct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key-not-used")
        from synapse.adapters.hosted import GeminiAdapter
        adapter = GeminiAdapter(model="gemini-2.5-flash")
        caps = adapter.capabilities
        assert caps.backend_id == "gemini"
        assert caps.tier == "hosted"
        assert caps.supports_midstream_inject is True
        assert caps.is_reasoning_model is False
        assert caps.model_id == "gemini-2.5-flash"

    def test_system_role_translated_to_system_instruction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key-not-used")
        from synapse.adapters.hosted import GeminiAdapter
        adapter = GeminiAdapter()
        messages = [
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        contents, system = adapter._prepare_messages(messages)
        assert system == "You are concise."
        assert len(contents) == 2
        # assistant -> model
        assert contents[1]["role"] == "model"
        assert contents[0]["role"] == "user"

    def test_estimate_cost_flash_model(self) -> None:
        from synapse.adapters.hosted.gemini_adapter import GeminiAdapter
        cost = GeminiAdapter.estimate_cost_usd("gemini-2.5-flash", 1_000_000, 500_000)
        # 0.075/M in + 0.30/M out * 0.5M = 0.075 + 0.15 = 0.225
        assert abs(cost - 0.225) < 0.001


class TestAdaptersImportable:
    def test_hosted_module_importable(self) -> None:
        # Should not raise even if no env keys set — SDK imports are lazy
        from synapse.adapters import hosted  # noqa: F401
        assert hasattr(hosted, "AnthropicAdapter")
        assert hasattr(hosted, "GeminiAdapter")
