"""InferenceAdapter Protocol — see spec/adapter.md for the canonical contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol, runtime_checkable

from synapse.messages import BackendCapabilities


@dataclass
class StreamHandle:
    """Opaque handle to an in-flight generation. Adapter-specific contents."""

    request_id: str
    original_messages: list[dict[str, Any]] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Token:
    text: str
    is_thinking: bool = False
    is_boundary: bool = False  # True at thinking->visible transitions for reasoning models


class BackendUnavailable(RuntimeError):
    """Raised when the backend cannot be reached. SDK falls back to no-coordination mode."""


class UnsupportedCapability(RuntimeError):
    """Raised when an operation is requested that the backend does not support
    (e.g., inject_and_continue on a reasoning model during thinking).
    """


@runtime_checkable
class InferenceAdapter(Protocol):
    capabilities: BackendCapabilities

    async def start_stream(
        self, messages: list[dict[str, Any]], params: dict[str, Any]
    ) -> StreamHandle: ...

    def read_tokens(self, handle: StreamHandle) -> AsyncIterator[Token]: ...

    async def inject_and_continue(
        self,
        handle: StreamHandle,
        injection: str,
        instruction: str = "Continue, accounting for the above.",
    ) -> StreamHandle: ...

    async def cancel(self, handle: StreamHandle) -> str: ...
