"""Inference adapters.

Phase 1: Mock (in-process scripted streaming).
Phase 2: Hosted tier (Anthropic, Gemini).
Phase 3: Native (vLLM via Modal), Local-API (Ollama).
"""

from synapse.adapters.base import (
    BackendUnavailable,
    InferenceAdapter,
    StreamHandle,
    Token,
    UnsupportedCapability,
)
from synapse.adapters.mock import MockAdapter

# Hosted adapters import the SDKs lazily — importing this module shouldn't fail
# even if anthropic / google-genai aren't installed. Re-export only via dotted
# path so users opt-in: `from synapse.adapters.hosted import AnthropicAdapter`.

__all__ = [
    "InferenceAdapter",
    "StreamHandle",
    "Token",
    "BackendUnavailable",
    "UnsupportedCapability",
    "MockAdapter",
]
