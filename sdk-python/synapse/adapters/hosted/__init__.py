"""Hosted-tier inference adapters.

These wrap proprietary APIs (Anthropic, OpenAI, Gemini). Mid-stream injection
on this tier is implemented via cached-restart: cancel the in-flight stream,
collect partial output, restart with the prefix prompt-cached + partial +
injection. Real overhead lands at ~1.10–1.30x per signal depending on cache
hit rate (see spec/adapter.md).
"""

from synapse.adapters.hosted.anthropic_adapter import AnthropicAdapter
from synapse.adapters.hosted.gemini_adapter import GeminiAdapter
from synapse.adapters.hosted.openai_adapter import OpenAIAdapter

__all__ = ["AnthropicAdapter", "GeminiAdapter", "OpenAIAdapter"]
