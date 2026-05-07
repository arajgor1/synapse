"""BYO-LLM configuration for Synapse v0.2.

Synapse never makes a paid LLM call without explicit caller config.
The user passes their existing LLM client (Anthropic / OpenAI / LangChain /
LiteLLM / Ollama / etc.) and Synapse uses it for any LLM-mediated
internal reasoning (scope inference fallback, belief divergence,
auto-merge, L3 semantic routing).

If ``set_llm()`` is never called, Synapse runs in **rules-only mode** —
L1 + L2 routing still work; LLM-mediated paths gracefully no-op with a
log message.

Public API:

    import synapse
    from anthropic import AsyncAnthropic

    # Simplest: pass your existing client
    synapse.set_llm(synapse.from_anthropic(AsyncAnthropic()))

    # Or any of the supported bridges
    synapse.set_llm(synapse.from_openai(openai_client))
    synapse.set_llm(synapse.from_litellm(model="anthropic/claude-haiku-4-5"))
    synapse.set_llm(synapse.from_langchain(ChatAnthropic(model="...")))

    # Or auto-detect from environment
    synapse.set_llm(synapse.auto_llm())

    # Or pass an InferenceAdapter directly (advanced)
    from synapse.adapters.anthropic import AnthropicAdapter
    synapse.set_llm(AnthropicAdapter(model="claude-haiku-4-5"))
"""
from __future__ import annotations

from .config import (
    LLMConfig,
    set_llm,
    get_llm,
    get_internal_llm,
    is_configured,
    clear,
)
from .bridges import (
    from_anthropic,
    from_openai,
    from_langchain,
    from_litellm,
    auto_llm,
)

__all__ = [
    "LLMConfig",
    "set_llm",
    "get_llm",
    "get_internal_llm",
    "is_configured",
    "clear",
    "from_anthropic",
    "from_openai",
    "from_langchain",
    "from_litellm",
    "auto_llm",
]
