"""InferenceAdapter Protocol — see spec/adapter.md for the canonical contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional, Protocol, runtime_checkable

from synapse.messages import BackendCapabilities


@dataclass
class TenantContext:
    """Identifies who owns a request in a multi-tenant deployment.

    All four fields are kept for adapter-side validation: an operation on
    `request_id` must be initiated by the same (tenant_id, agent_id, session_id)
    that started the stream. Cross-tenant access is rejected.
    """

    tenant_id: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None

    def matches(self, other: "TenantContext") -> bool:
        return (
            self.tenant_id == other.tenant_id
            and self.agent_id == other.agent_id
            and self.session_id == other.session_id
        )


@dataclass
class StreamHandle:
    """Opaque handle to an in-flight generation. Adapter-specific contents."""

    request_id: str
    original_messages: list[dict[str, Any]] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    tenant: TenantContext = field(default_factory=TenantContext)


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


class TenantViolation(RuntimeError):
    """Raised when an operation tries to act on a request_id that belongs to a
    different (tenant_id, agent_id, session_id) than the caller.

    Native and Local-API adapters with `multi_tenant_isolation = "request_id"`
    MUST raise this on cross-tenant access.
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
