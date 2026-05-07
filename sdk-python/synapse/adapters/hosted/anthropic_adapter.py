"""Anthropic hosted adapter — Sonnet/Haiku/Opus via the Anthropic Python SDK.

Implements the cached-restart injection pattern from spec/adapter.md:
  cancel current stream -> collect partial -> restart with cache_control breakpoint
  on system+history -> append [partial output][SYNAPSE INTERRUPT][continuation]

Requires ANTHROPIC_API_KEY env var. SDK throws BackendUnavailable if missing.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from synapse.adapters.base import (
    BackendUnavailable,
    InferenceAdapter,
    StreamHandle,
    Token,
    UnsupportedCapability,
)
from synapse.messages import BackendCapabilities

logger = logging.getLogger(__name__)


# Per-1M-token pricing as of mid-2026. Adapter only uses these for the
# COST_REPORT estimate; users should override or let the framework auto-fetch
# in a future version.
_PRICING = {
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00, "cache_read": 0.30},
    "claude-haiku-4-5-20251001":  {"input": 1.00, "output": 5.00,  "cache_read": 0.10},
    "claude-opus-4-1-20250805":   {"input": 15.00, "output": 75.00, "cache_read": 1.50},
}


class AnthropicAdapter:
    """Hosted-tier adapter for Anthropic.

    Capability flags reflect Anthropic's streaming + prompt-cache reality:
    - supports_midstream_inject: True (via cached-restart)
    - supports_partial_preservation: True (clean stream abort)
    - prompt_cache_available: True
    """

    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        api_key: Optional[str] = None,
        max_tokens: int = 1024,
        cache_breakpoints: bool = True,
    ) -> None:
        try:
            from anthropic import AsyncAnthropic  # type: ignore[import-not-found]
        except ImportError as e:
            raise BackendUnavailable(
                "anthropic package not installed. `pip install anthropic`."
            ) from e

        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise BackendUnavailable(
                "ANTHROPIC_API_KEY not set. Export it or pass api_key=..."
            )

        self._client = AsyncAnthropic(api_key=key)
        self._model = model
        self._max_tokens = max_tokens
        self._cache_breakpoints = cache_breakpoints
        self._streams: dict[str, dict[str, Any]] = {}

        self.capabilities = BackendCapabilities(
            backend_id="anthropic",
            tier="hosted",
            supports_midstream_inject=True,
            supports_partial_preservation=True,
            is_reasoning_model=False,
            prompt_cache_available=True,
            avg_overhead_per_signal=1.15,
            multi_tenant_isolation="process",
            model_id=model,
        )

    # -----------------------------------------------------------------
    # Stream lifecycle
    # -----------------------------------------------------------------
    async def start_stream(
        self, messages: list[dict[str, Any]], params: dict[str, Any]
    ) -> StreamHandle:
        rid = uuid.uuid4().hex
        # Apply cache_control to the last system block (if any) and the most
        # recent user message — prompt-cache prefix on restart is what makes
        # cached-restart cheap.
        anthropic_messages, system = self._prepare_messages(messages)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": anthropic_messages,
            "max_tokens": params.get("max_tokens", self._max_tokens),
        }
        if system is not None:
            kwargs["system"] = system

        # Open the streaming context manager — keep handle open until cancel/done.
        ctx = self._client.messages.stream(**kwargs)
        stream = await ctx.__aenter__()
        self._streams[rid] = {
            "ctx": ctx,
            "stream": stream,
            "partial": "",
            "started_at": time.time(),
            "params": params,
            "messages": messages,
            "system": system,
        }
        return StreamHandle(
            request_id=rid,
            original_messages=list(messages),
            params=dict(params),
            extra={"system": system},
        )

    def read_tokens(self, handle: StreamHandle) -> AsyncIterator[Token]:
        return self._read_tokens(handle)

    async def _read_tokens(self, handle: StreamHandle) -> AsyncIterator[Token]:
        state = self._streams.get(handle.request_id)
        if state is None:
            raise RuntimeError(f"Unknown request: {handle.request_id}")
        stream = state["stream"]

        try:
            async for event in stream:
                # Anthropic stream events: content_block_delta carries a delta
                # object with its own type field. Only 'text_delta' is plain
                # generated text. Other delta types we currently ignore:
                #   - 'input_json_delta' (tool-use args streaming)
                #   - 'thinking_delta'   (extended-thinking models)
                # Per Anthropic streaming docs.
                event_type = getattr(event, "type", None)
                if event_type != "content_block_delta":
                    continue
                delta = getattr(event, "delta", None)
                if delta is None:
                    continue
                if getattr(delta, "type", None) != "text_delta":
                    continue
                text = getattr(delta, "text", None)
                if text:
                    state["partial"] += text
                    yield Token(text=text)
        except Exception as e:
            # Stream cancelled or errored. Caller can still read state["partial"].
            logger.debug("Stream %s ended: %s", handle.request_id, e)

    async def inject_and_continue(
        self,
        handle: StreamHandle,
        injection: str,
        instruction: str = "Continue, accounting for the above.",
    ) -> StreamHandle:
        """Cached-restart injection.

        Cancels current stream, then issues a NEW request with:
            [system + history (cache breakpoint here)] +
            [assistant: partial output] +
            [user: SYNAPSE INTERRUPT + injection + instruction]

        The cache breakpoint means system+history hits cache on restart,
        keeping cost overhead in the ~1.10x range.
        """
        partial = await self.cancel(handle)
        # Build the continuation messages. Add cache_control on the last
        # system block / penultimate user message so the prefix caches.
        original = list(handle.original_messages)
        new_messages: list[dict[str, Any]] = []

        # Mark the last item in original as a cache breakpoint
        if original and self._cache_breakpoints:
            tail = dict(original[-1])
            content = tail.get("content")
            if isinstance(content, str):
                tail["content"] = [
                    {"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}
                ]
            elif isinstance(content, list) and content:
                last_block = dict(content[-1])
                last_block["cache_control"] = {"type": "ephemeral"}
                tail["content"] = list(content[:-1]) + [last_block]
            new_messages = list(original[:-1]) + [tail]
        else:
            new_messages = list(original)

        if partial.strip():
            new_messages.append({"role": "assistant", "content": partial})
        new_messages.append({
            "role": "user",
            "content": (
                f"[SYNAPSE INTERRUPT]\n{injection}\n\n"
                f"{instruction}"
            ),
        })

        return await self.start_stream(new_messages, handle.params)

    async def cancel(self, handle: StreamHandle) -> str:
        import asyncio as _asyncio
        state = self._streams.pop(handle.request_id, None)
        if state is None:
            return ""
        # __aexit__ on the streaming context can hang waiting for the SSE
        # stream to drain when we stopped reading mid-flight. Bound it with
        # a timeout so cancel() always returns promptly.
        try:
            await _asyncio.wait_for(
                state["ctx"].__aexit__(None, None, None), timeout=1.5,
            )
        except _asyncio.TimeoutError:
            logger.debug("Cancel timed out closing stream %s; proceeding", handle.request_id)
        except Exception as e:
            logger.debug("Cancel cleanup error (non-fatal): %s", e)
        return state["partial"]

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------
    def _prepare_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], Optional[str | list[dict[str, Any]]]]:
        """Anthropic separates `system` from `messages`. Extract it if present."""
        system: Optional[str | list[dict[str, Any]]] = None
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.get("role") == "system":
                # First system message becomes the top-level system arg
                if system is None:
                    system = m.get("content")
            else:
                out.append(m)
        return out, system

    @staticmethod
    def estimate_cost_usd(
        model: str, tokens_in: int, tokens_out: int, tokens_cached: int = 0
    ) -> float:
        p = _PRICING.get(model)
        if p is None:
            return 0.0
        non_cached_in = max(0, tokens_in - tokens_cached)
        return (
            non_cached_in * p["input"] / 1_000_000
            + tokens_cached * p["cache_read"] / 1_000_000
            + tokens_out * p["output"] / 1_000_000
        )
