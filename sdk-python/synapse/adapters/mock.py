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

from synapse.adapters._isolation import RequestIdIsolatedMixin
from synapse.adapters.base import (
    InferenceAdapter,
    StreamHandle,
    TenantContext,
    Token,
)
from synapse.messages import BackendCapabilities

logger = logging.getLogger(__name__)


@dataclass
class MockStreamState:
    response: str
    delay_per_token_ms: int
    cancelled: bool = False
    emitted_so_far: str = ""


class MockAdapter(RequestIdIsolatedMixin):
    """Simulates a streaming LLM. Configurable scripted response per request.

    Capabilities are advertised as 'native' tier with mid-stream inject support
    so the SDK can exercise the full append-and-continue path. Defaults to
    `multi_tenant_isolation='request_id'` so tenant-isolation tests can use it."""

    def __init__(
        self,
        scripted_response: str = "Mock response. No real LLM was called.",
        delay_per_token_ms: int = 5,
        multi_tenant: bool = True,
    ) -> None:
        self._default_response = scripted_response
        self._default_delay = delay_per_token_ms
        self._streams: dict[str, MockStreamState] = {}
        self._tenant_index: dict[str, TenantContext] = {}
        self.capabilities = BackendCapabilities(
            backend_id="mock",
            tier="native",
            supports_midstream_inject=True,
            supports_partial_preservation=True,
            is_reasoning_model=False,
            prompt_cache_available=False,
            avg_overhead_per_signal=1.0,
            multi_tenant_isolation="request_id" if multi_tenant else "process",
            model_id="mock-llm-1",
        )

    async def start_stream(
        self, messages: list[dict[str, Any]], params: dict[str, Any]
    ) -> StreamHandle:
        rid = uuid.uuid4().hex
        response = params.get("scripted_response", self._default_response)
        delay = params.get("delay_per_token_ms", self._default_delay)
        self._streams[rid] = MockStreamState(response=response, delay_per_token_ms=delay)
        # Stamp tenant from params (the SDK passes tenant context via params['tenant'])
        tenant: Optional[TenantContext] = params.get("tenant")
        self._stamp_tenant(rid, tenant)
        return StreamHandle(
            request_id=rid,
            original_messages=list(messages),
            params=dict(params),
            tenant=tenant or TenantContext(),
        )

    async def read_tokens(self, handle: StreamHandle) -> AsyncIterator[Token]:  # type: ignore[override]
        self._check_tenant(handle, handle.tenant)
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
        self._check_tenant(handle, handle.tenant)
        # Mock "append-and-continue": cancel the current stream, capture partial,
        # start a new one whose scripted response acknowledges the injection.
        partial = await self.cancel(handle)
        new_response = (
            f"[continuing after partial: '{partial.strip()}'] "
            f"acknowledged signal: {injection}. "
            f"{instruction}"
        )
        # Carry tenant through to the new stream
        params = {**handle.params, "scripted_response": new_response}
        if "tenant" not in params and handle.tenant:
            params["tenant"] = handle.tenant
        return await self.start_stream(
            messages=handle.original_messages,
            params=params,
        )

    async def cancel(self, handle: StreamHandle) -> str:
        self._check_tenant(handle, handle.tenant)
        state = self._streams.get(handle.request_id)
        self._release_tenant(handle.request_id)
        if state is None:
            return ""
        state.cancelled = True
        return state.emitted_so_far
