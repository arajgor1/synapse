"""OpenAI hosted adapter.

Same cached-restart injection pattern as Anthropic. OpenAI's prompt-cache
fires automatically on prefixes >=1024 tokens (no manual cache_control
markers needed), so the adapter doesn't have to do anything special to
benefit from it.

Requires OPENAI_API_KEY env var.
Reasoning models (o1, o3) are detected by model name and get the
is_reasoning_model flag + supports_midstream_inject=False.

Untested in this session (no OPENAI_API_KEY available); all behavior
follows the same shape as the Anthropic adapter, which IS verified.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any, AsyncIterator, Optional

from synapse.adapters.base import (
    BackendUnavailable,
    InferenceAdapter,
    StreamHandle,
    Token,
)
from synapse.messages import BackendCapabilities

logger = logging.getLogger(__name__)


# Per-1M-token pricing (mid-2026 list).
_PRICING = {
    "gpt-4o-mini":       {"input": 0.15,  "output": 0.60},
    "gpt-4o":            {"input": 2.50,  "output": 10.00},
    "gpt-4.1":           {"input": 2.00,  "output": 8.00},
    "gpt-4.1-mini":      {"input": 0.40,  "output": 1.60},
    "o1":                {"input": 15.00, "output": 60.00},
    "o3":                {"input": 30.00, "output": 120.00},
    "o3-mini":           {"input": 1.10,  "output": 4.40},
}

_REASONING_MODELS = {"o1", "o3", "o3-mini", "o1-mini", "o1-preview"}


class OpenAIAdapter:
    """Hosted-tier adapter for OpenAI."""

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: Optional[str] = None,
        max_tokens: int = 1024,
    ) -> None:
        try:
            from openai import AsyncOpenAI  # type: ignore[import-not-found]
        except ImportError as e:
            raise BackendUnavailable(
                "openai package not installed. `pip install openai`."
            ) from e

        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise BackendUnavailable("OPENAI_API_KEY not set.")

        self._client = AsyncOpenAI(api_key=key)
        self._model = model
        self._max_tokens = max_tokens
        self._streams: dict[str, dict[str, Any]] = {}

        is_reasoning = any(model.startswith(rm) for rm in _REASONING_MODELS)
        self.capabilities = BackendCapabilities(
            backend_id="openai",
            tier="hosted",
            supports_midstream_inject=not is_reasoning,
            supports_partial_preservation=True,
            is_reasoning_model=is_reasoning,
            prompt_cache_available=True,  # automatic for >1024 tok prefixes
            avg_overhead_per_signal=1.20 if not is_reasoning else 1.40,
            multi_tenant_isolation="process",
            model_id=model,
        )

    async def start_stream(
        self, messages: list[dict[str, Any]], params: dict[str, Any]
    ) -> StreamHandle:
        rid = uuid.uuid4().hex
        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=params.get("max_tokens", self._max_tokens),
                stream=True,
            )
        except Exception as e:
            raise BackendUnavailable(f"OpenAI start_stream failed: {e}") from e

        self._streams[rid] = {
            "stream": stream,
            "partial": "",
            "started_at": time.time(),
            "params": params,
            "messages": messages,
            "cancelled": False,
        }
        return StreamHandle(
            request_id=rid,
            original_messages=list(messages),
            params=dict(params),
        )

    def read_tokens(self, handle: StreamHandle) -> AsyncIterator[Token]:
        return self._read_tokens(handle)

    async def _read_tokens(self, handle: StreamHandle) -> AsyncIterator[Token]:
        state = self._streams.get(handle.request_id)
        if state is None:
            raise RuntimeError(f"Unknown request: {handle.request_id}")
        stream = state["stream"]
        try:
            async for chunk in stream:
                if state["cancelled"]:
                    break
                # OpenAI chunk shape: chunk.choices[0].delta.content
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                text = getattr(delta, "content", None) if delta else None
                if text:
                    state["partial"] += text
                    yield Token(text=text)
        except Exception as e:
            logger.warning("OpenAI stream %s errored: %s", handle.request_id, e)
            state["error"] = str(e)

    async def inject_and_continue(
        self,
        handle: StreamHandle,
        injection: str,
        instruction: str = "Continue, accounting for the above.",
    ) -> StreamHandle:
        partial = await self.cancel(handle)
        new_messages = list(handle.original_messages)
        if partial.strip():
            new_messages.append({"role": "assistant", "content": partial})
        new_messages.append({
            "role": "user",
            "content": f"[SYNAPSE INTERRUPT]\n{injection}\n\n{instruction}",
        })
        return await self.start_stream(new_messages, handle.params)

    async def cancel(self, handle: StreamHandle) -> str:
        state = self._streams.pop(handle.request_id, None)
        if state is None:
            return ""
        state["cancelled"] = True
        try:
            stream = state["stream"]
            if hasattr(stream, "close"):
                await stream.close()
        except Exception:
            pass
        return state["partial"]

    @staticmethod
    def estimate_cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
        p = _PRICING.get(model)
        if p is None:
            return 0.0
        return tokens_in * p["input"] / 1_000_000 + tokens_out * p["output"] / 1_000_000
