"""Bridges from popular vendor clients to Synapse's InferenceAdapter.

Each ``from_*`` accepts the vendor's existing client object (so the user
keeps their model choice, API key, base URL, retry/timeout config, etc.)
and returns an adapter Synapse can use.

These bridges are LIGHTWEIGHT: they reuse the existing Synapse adapters
(``AnthropicAdapter``, ``OpenAIAdapter``, ``GeminiAdapter``, ``OllamaAdapter``)
where possible, just constructed from the user's already-configured
client instead of from environment variables.

Lazy imports throughout — Synapse never depends on ``langchain`` or
``litellm`` unless the user explicitly bridges through them.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from synapse.adapters.base import InferenceAdapter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------
def from_anthropic(
    client: Optional[Any] = None,
    *,
    model: str = "claude-haiku-4-5-20251001",
    api_key: Optional[str] = None,
) -> InferenceAdapter:
    """Wrap an Anthropic client (or create one from env) for Synapse.

    Examples:
        from anthropic import AsyncAnthropic
        synapse.set_llm(synapse.from_anthropic(AsyncAnthropic()))

        # Or skip the client and let Synapse build one
        synapse.set_llm(synapse.from_anthropic(model="claude-haiku-4-5-20251001"))
    """
    from synapse.adapters.hosted.anthropic_adapter import AnthropicAdapter

    adapter = AnthropicAdapter(model=model, api_key=api_key)
    if client is not None:
        # If the user passed a configured client, swap it in. This preserves
        # their retry config, base_url, default_headers, etc.
        adapter._client = client
    return adapter


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------
def from_openai(
    client: Optional[Any] = None,
    *,
    model: str = "gpt-4o-mini",
    api_key: Optional[str] = None,
) -> InferenceAdapter:
    """Wrap an OpenAI / Azure OpenAI / OpenAI-compatible client.

    Examples:
        from openai import AsyncOpenAI
        synapse.set_llm(synapse.from_openai(AsyncOpenAI()))

        # Self-hosted vLLM via OpenAI-compatible endpoint
        client = AsyncOpenAI(base_url="http://localhost:8000/v1", api_key="sk-local")
        synapse.set_llm(synapse.from_openai(client, model="llama3.1-8b"))
    """
    from synapse.adapters.hosted.openai_adapter import OpenAIAdapter

    adapter = OpenAIAdapter(model=model, api_key=api_key)
    if client is not None:
        adapter._client = client
    return adapter


# ---------------------------------------------------------------------------
# LangChain / LangGraph
# ---------------------------------------------------------------------------
def from_langchain(llm: Any) -> InferenceAdapter:
    """Wrap a LangChain ``BaseLanguageModel`` so Synapse can call it.

    Works with any LangChain-compatible chat model: ``ChatAnthropic``,
    ``ChatOpenAI``, ``ChatGroq``, ``ChatVertexAI``, ``ChatOllama``, etc.
    Reuses the user's existing model+config.

    Example:
        from langchain_anthropic import ChatAnthropic
        synapse.set_llm(synapse.from_langchain(ChatAnthropic(model="...")))
    """
    return _LangChainBridgeAdapter(llm)


# ---------------------------------------------------------------------------
# LiteLLM (universal across 100+ providers)
# ---------------------------------------------------------------------------
def from_litellm(
    *,
    model: str,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    **extra: Any,
) -> InferenceAdapter:
    """Wrap a LiteLLM-routable model spec (e.g. "anthropic/claude-haiku-4-5").

    LiteLLM normalizes 100+ providers behind one client. Synapse stays
    single-dependency by lazy-importing it only when this bridge is used.

    Example:
        synapse.set_llm(synapse.from_litellm(model="anthropic/claude-haiku-4-5"))
    """
    return _LiteLLMBridgeAdapter(model=model, api_key=api_key, api_base=api_base, extra=extra)


# ---------------------------------------------------------------------------
# Auto-detect (best-effort) — picks the first provider it finds keys for
# ---------------------------------------------------------------------------
def auto_llm() -> InferenceAdapter:
    """Pick the cheapest available provider based on env keys.

    Order: Anthropic → OpenAI → Gemini → Ollama (local).
    Picks the cheapest model in that family by default.

    Raises:
        RuntimeError if no provider can be configured.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        logger.info("synapse.auto_llm: using Anthropic Haiku 4.5")
        return from_anthropic(model="claude-haiku-4-5-20251001")
    if os.environ.get("OPENAI_API_KEY"):
        logger.info("synapse.auto_llm: using OpenAI gpt-4o-mini")
        return from_openai(model="gpt-4o-mini")
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        from synapse.adapters.hosted.gemini_adapter import GeminiAdapter
        logger.info("synapse.auto_llm: using Gemini 2.5 Flash")
        return GeminiAdapter(model="gemini-2.5-flash")
    if os.environ.get("OLLAMA_HOST") or _ollama_local_running():
        from synapse.adapters.local.ollama_adapter import OllamaAdapter
        logger.info("synapse.auto_llm: using local Ollama (llama3.1:8b)")
        return OllamaAdapter(model="llama3.1:8b")
    raise RuntimeError(
        "synapse.auto_llm: no LLM provider keys found in environment. "
        "Set ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY, run a "
        "local Ollama, or call synapse.set_llm(...) explicitly."
    )


def _ollama_local_running() -> bool:
    try:
        import httpx  # type: ignore
        r = httpx.get("http://localhost:11434/api/tags", timeout=0.5)
        return r.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Internal: minimal InferenceAdapter shim for LangChain-wrapped LLMs.
# Synapse's L3-router and audit-mode scope-inference fallback only need
# a synchronous-style "given prompt, return text" call. We don't reproduce
# the full streaming surface here — just enough for the LLM-mediated
# reasoning paths.
# ---------------------------------------------------------------------------
class _LangChainBridgeAdapter:
    """Best-effort adapter for any LangChain BaseLanguageModel."""

    def __init__(self, llm: Any) -> None:
        from synapse.messages import BackendCapabilities

        self._llm = llm
        self.capabilities = BackendCapabilities(
            backend_id=f"langchain:{type(llm).__name__}",
            tier="hosted",
            supports_midstream_inject=False,
            supports_partial_preservation=False,
            prompt_cache_available=False,
            supports_thinking=False,
            multi_tenant_isolation="none",
        )

    async def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        **_: Any,
    ) -> str:
        """Synapse-internal shorthand: prompt → text."""
        from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

        lc_messages = []
        for m in messages:
            role = m.get("role")
            content = m.get("content", "")
            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=content))
            else:
                lc_messages.append(HumanMessage(content=content))

        result = await self._llm.ainvoke(lc_messages)
        return getattr(result, "content", str(result))

    # Placeholder streaming methods — Synapse's L3 + audit paths only call
    # .generate(). Streaming raises UnsupportedCapability with a clear message.
    async def start_stream(self, *args, **kwargs):  # pragma: no cover
        from synapse.adapters.base import UnsupportedCapability
        raise UnsupportedCapability(
            "LangChain bridge supports .generate() only. Use a native adapter "
            "(AnthropicAdapter / OpenAIAdapter) for streaming."
        )

    def read_tokens(self, handle):  # pragma: no cover
        async def _empty():
            if False:
                yield None
        return _empty()

    async def inject_and_continue(self, handle, injection, instruction=""):  # pragma: no cover
        from synapse.adapters.base import UnsupportedCapability
        raise UnsupportedCapability("LangChain bridge does not support inject_and_continue.")

    async def cancel(self, *args, **kwargs):  # pragma: no cover
        return None


class _LiteLLMBridgeAdapter:
    def __init__(self, model: str, api_key: Optional[str], api_base: Optional[str], extra: dict) -> None:
        from synapse.messages import BackendCapabilities
        try:
            import litellm  # type: ignore[import-not-found]
        except ImportError as e:
            raise RuntimeError(
                "litellm not installed. `pip install litellm`."
            ) from e
        self._litellm = litellm
        self._model = model
        self._api_key = api_key
        self._api_base = api_base
        self._extra = extra
        self.capabilities = BackendCapabilities(
            backend_id=f"litellm:{model}",
            tier="hosted",
            supports_midstream_inject=False,
            supports_partial_preservation=False,
            prompt_cache_available=False,
            supports_thinking=False,
            multi_tenant_isolation="none",
        )

    async def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        **_: Any,
    ) -> str:
        kwargs = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            **self._extra,
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._api_base:
            kwargs["api_base"] = self._api_base
        resp = await self._litellm.acompletion(**kwargs)
        return resp.choices[0].message.content or ""

    async def start_stream(self, *args, **kwargs):  # pragma: no cover
        from synapse.adapters.base import UnsupportedCapability
        raise UnsupportedCapability("LiteLLM bridge supports .generate() only")

    def read_tokens(self, handle):  # pragma: no cover
        async def _empty():
            if False:
                yield None
        return _empty()

    async def inject_and_continue(self, handle, injection, instruction=""):  # pragma: no cover
        from synapse.adapters.base import UnsupportedCapability
        raise UnsupportedCapability("LiteLLM bridge does not support inject_and_continue.")

    async def cancel(self, *args, **kwargs):  # pragma: no cover
        return None
