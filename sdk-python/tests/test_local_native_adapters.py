"""Tests for Phase 3 adapters — Ollama (local-API) and vLLM-via-Modal (native).

All mock-only; no real Ollama / Modal calls. Live integration is via the
multi-backend demo (examples/multi_backend_demo.py) and the modal smoke-test
(`modal run runtime/modal/vllm_engine.py::smoke_test`).
"""

from __future__ import annotations

import pytest

from synapse.adapters.base import BackendUnavailable


class TestOllamaAdapter:
    def test_capabilities_correct(self) -> None:
        from synapse.adapters.local import OllamaAdapter
        adapter = OllamaAdapter(model="llama3.2:3b")
        caps = adapter.capabilities
        assert caps.backend_id == "ollama"
        assert caps.tier == "local_api"
        assert caps.supports_midstream_inject is True
        assert caps.is_reasoning_model is False
        assert 1.0 <= caps.avg_overhead_per_signal < 1.15
        assert caps.model_id == "llama3.2:3b"

    def test_messages_to_prompt_format(self) -> None:
        from synapse.adapters.local import OllamaAdapter
        prompt = OllamaAdapter._messages_to_prompt([
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello."},
        ])
        assert "[SYSTEM]" in prompt
        assert "Be brief." in prompt
        assert "[USER]" in prompt
        assert "Hi" in prompt
        assert "[ASSISTANT]" in prompt
        assert "Hello." in prompt
        # Final ASSISTANT cue
        assert prompt.rstrip().endswith("[ASSISTANT]")

    def test_messages_with_block_content(self) -> None:
        from synapse.adapters.local import OllamaAdapter
        prompt = OllamaAdapter._messages_to_prompt([
            {"role": "user", "content": [{"type": "text", "text": "block content"}]},
        ])
        assert "block content" in prompt


class TestVLLMModalAdapter:
    def test_capabilities_correct(self) -> None:
        from synapse.adapters.native import VLLMModalAdapter
        adapter = VLLMModalAdapter(model="Qwen/Qwen2.5-0.5B-Instruct")
        caps = adapter.capabilities
        assert caps.backend_id == "vllm-modal"
        assert caps.tier == "native"
        assert caps.supports_midstream_inject is True
        assert caps.multi_tenant_isolation == "request_id"
        assert caps.avg_overhead_per_signal < 1.10
        assert caps.model_id == "Qwen/Qwen2.5-0.5B-Instruct"

    def test_messages_to_prompt_format(self) -> None:
        from synapse.adapters.native import VLLMModalAdapter
        prompt = VLLMModalAdapter._messages_to_prompt([
            {"role": "system", "content": "Be terse."},
            {"role": "user", "content": "Test"},
        ])
        assert "[SYSTEM]" in prompt
        assert "[USER]" in prompt
        assert prompt.rstrip().endswith("[ASSISTANT]")


class TestPhaseThreeAdaptersImportable:
    def test_local_module_importable(self) -> None:
        from synapse.adapters import local
        assert hasattr(local, "OllamaAdapter")

    def test_native_module_importable(self) -> None:
        from synapse.adapters import native
        assert hasattr(native, "VLLMModalAdapter")

    def test_all_tiers_capability_distinct(self) -> None:
        """Each tier should have characteristic overhead and isolation defaults."""
        from synapse.adapters import MockAdapter
        from synapse.adapters.local import OllamaAdapter
        from synapse.adapters.native import VLLMModalAdapter

        mock = MockAdapter()
        ollama = OllamaAdapter()
        vllm = VLLMModalAdapter()

        # Native should be the fastest (lowest overhead)
        assert vllm.capabilities.avg_overhead_per_signal <= ollama.capabilities.avg_overhead_per_signal
        # All three support midstream inject
        assert mock.capabilities.supports_midstream_inject
        assert ollama.capabilities.supports_midstream_inject
        assert vllm.capabilities.supports_midstream_inject
