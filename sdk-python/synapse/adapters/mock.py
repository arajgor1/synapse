"""Mock inference adapter — for Phase 1 demos and tests.

Doesn't talk to any LLM. Emits a configurable scripted response token-by-token,
supports cancel-and-restart-style injection. Sufficient for proving the
coordination protocol works end-to-end without API costs.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from synapse.adapters.base import InferenceAdapter, StreamHandle, Token
from synapse.messages import BackendCapabilities

logger = logging.getLogger(__name__)


@dataclass
class MockStreamState:
    response: str
    delay_per_token_ms: int
    cancelled: bool = False
    emitted_so_far: str = ""


class MockAdapter:
    """Simulates a streaming LLM. Configurable scripted response per request.

    Capabilities are advertised as 'native' tier with mid-stream inject support
    so the SDK can exercise the full append-and-continue path."""

    capabilities = BackendCapabilities(
        backend_id="mock",
        tier="native",
        supports_midstream_inject=True,
        supports_partial_preservation=True,
        is_reasoning_model=False,
        prompt_cache_available=False,
        avg_overhead_per_signal=1.0,
        multi_tenant_isolation="process",
        model_id="mock-llm-1",
    )

    def __init__(
        self,
        scripted_response: str = "Mock response. No real LLM was called.",
        delay_per_token_ms: int = 5,
    ) -> None:
        self._default_response = scripted_response
        self._default_delay = delay_per_token_ms
        self._streams: dict[str, MockStreamState] = {}

    async def start_stream(
        self, messages: list[dict[str, Any]], params: dict[str, Any]
    ) -> StreamHandle:
        rid = uuid.uuid4().hex
        response = params.get("scripted_response", self._default_response)
        delay = params.get("delay_per_token_ms", self._default_delay)
        self._streams[rid] = MockStreamState(response=response, delay_per_token_ms=delay)
        return StreamHandle(request_id=rid, original_messages=list(messages), params=dict(params))

    async def read_tokens(self, handle: StreamHandle) -> AsyncIterator[Token]:  # type: ignore[override]
        state = self._streams.get(handle.request_id)
        if state is None:
            raise RuntimeError(f"Unknown request: {handle.request_id}")
        # Stream by simple whitespace tokens for visibility.
        for word in state.response.split():
            if state.cancelled:
                return
            await asyncio.sleep(state.delay_per_token_ms / 1000)
            state.emitted_so_far = (state.emitted_so_far + " " + word).strip()
            yield Token(text=word + " ")

    async def inject_and_continue(
        self,
        handle: StreamHandle,
        injection: str,
        instruction: str = "Continue, accounting for the above.",
    ) -> StreamHandle:
        # Mock "append-and-continue": cancel the current stream, capture partial,
        # start a new one whose scripted response acknowledges the injection.
        partial = await self.cancel(handle)
        new_response = (
            f"[continuing after partial: '{partial.strip()}'] "
            f"acknowledged signal: {injection}. "
            f"{instruction}"
        )
        return await self.start_stream(
            messages=handle.original_messages,
            params={**handle.params, "scripted_response": new_response},
        )

    async def cancel(self, handle: StreamHandle) -> str:
        state = self._streams.get(handle.request_id)
        if state is None:
            return ""
        state.cancelled = True
        return state.emitted_so_far
