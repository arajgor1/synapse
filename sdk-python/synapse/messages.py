"""Pydantic models for the eight Synapse message types + envelope.

Mirrors spec/protocol-v1.0/*.schema.json. The schemas are the canonical contract;
these models are convenience for Python consumers and MUST stay in sync.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

# python-ulid is part of the [live] extras. Audit-only installs don't ship
# Redis/Postgres/ULID — but they may still want to validate envelopes they
# read from a trace file. Provide a fallback ULID-shaped string for those
# paths, and only raise at MINT time (Envelope.make()) if real ULIDs aren't
# available.
try:
    from ulid import ULID  # type: ignore[import-not-found]
    _ULID_AVAILABLE = True
except ImportError:  # pragma: no cover — exercised only in audit-only installs
    ULID = None  # type: ignore[misc,assignment]
    _ULID_AVAILABLE = False


def _ulid_str_or_raise() -> str:
    if not _ULID_AVAILABLE:
        raise ImportError(
            "Envelope.make() requires the 'live' extras. "
            "Install with `pip install synapse-protocol-py[live]` to mint envelopes. "
            "If you only need to AUDIT existing traces, use synapse.audit "
            "directly — it doesn't need this code path."
        )
    return str(ULID())  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Type tags
# ---------------------------------------------------------------------------
class MessageType(str, Enum):
    THOUGHT = "THOUGHT"
    INTENTION = "INTENTION"
    PIVOT = "PIVOT"
    BELIEF = "BELIEF"
    BLOCK = "BLOCK"
    CONFLICT = "CONFLICT"
    RESOLUTION = "RESOLUTION"
    COST_REPORT = "COST_REPORT"


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------
class Intention(BaseModel):
    """Pre-action declaration. Drives all conflict detection."""

    action: dict[str, Any]
    scope: list[str] = Field(min_length=1)
    expected_outcome: str
    estimated_duration_ms: Optional[int] = None
    blocking: bool = False
    uncertainty: Optional[str] = None
    blocks_others: list[str] = Field(default_factory=list)


class Thought(BaseModel):
    summary: str = Field(max_length=2000)
    raw_excerpt: Optional[str] = None
    topics: list[str] = Field(default_factory=list)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class Pivot(BaseModel):
    from_intention_id: str
    to_intention: Intention
    reason: str
    affects: list[str] = Field(default_factory=list)
    frees: list[str] = Field(default_factory=list)


class Belief(BaseModel):
    key: str
    value: Any
    confidence: float = Field(ge=0.0, le=1.0)
    source: Literal["observed", "inferred", "assumed"]
    evidence: Optional[str] = None


class Block(BaseModel):
    blocker: str
    needed: str
    attempted: list[str] = Field(default_factory=list)
    urgency: Literal["low", "medium", "high"] = "medium"
    topics: list[str] = Field(default_factory=list)


class ConflictingIntention(BaseModel):
    intention_id: str
    agent_id: str
    scope: list[str]
    started_at_ms: Optional[int] = None


class Conflict(BaseModel):
    intention_id: str
    conflicting_intentions: list[ConflictingIntention] = Field(min_length=1)
    kind: Literal[
        "scope_overlap",
        "stale_base_overwrite",
        "exclusive_claim",
        "policy_block",
        "dependency_wait",
    ]
    overlapping_scopes: list[str] = Field(default_factory=list)
    suggested_resolution: Optional[
        Literal["wait", "pivot", "narrow_scope", "coordinate", "abort"]
    ] = None
    rationale: Optional[str] = None


class ResolutionError(BaseModel):
    kind: str
    message: str
    recoverable: bool = False


class Resolution(BaseModel):
    intention_id: str
    outcome: Literal["success", "failure", "partial"]
    state_diff: dict[str, Any] = Field(default_factory=dict)
    side_effects: list[str] = Field(default_factory=list)
    next_intention_hint: Optional[str] = None
    error: Optional[ResolutionError] = None


class CostReport(BaseModel):
    signal_id: str
    mechanism: Literal[
        "inbox_at_decision_point",
        "native_kv_append",
        "local_api_context_resume",
        "hosted_cached_restart",
        "pre_execution_gate",
    ]
    tokens_billed: int = Field(ge=0)
    tokens_cached: Optional[int] = Field(default=None, ge=0)
    wall_clock_ms: int = Field(ge=0)
    estimated_usd: Optional[float] = Field(default=None, ge=0.0)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------
class Envelope(BaseModel):
    """Wraps every Synapse message. Validate this; the payload schema is selected by `type`."""

    msg_id: str
    type: MessageType
    version: str = "1.0"
    agent_id: str
    session_id: str
    task_id: Optional[str] = None
    parent_msg_id: Optional[str] = None
    timestamp_ms: int
    payload: dict[str, Any]
    tenant_id: Optional[str] = None

    @field_validator("msg_id", "parent_msg_id")
    @classmethod
    def _validate_ulid(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        # ULIDs are 26 chars in Crockford base32. Skip strict validation if
        # python-ulid isn't installed (audit-only install case) — callers
        # building envelopes from trace exports only need them to parse.
        if _ULID_AVAILABLE:
            ULID.from_str(v)  # type: ignore[union-attr]
        else:
            if not isinstance(v, str) or len(v) != 26:
                raise ValueError(f"msg_id must be a 26-char ULID string, got {v!r}")
        return v

    @classmethod
    def make(
        cls,
        *,
        type: MessageType,
        agent_id: str,
        session_id: str,
        payload: BaseModel | dict[str, Any],
        task_id: Optional[str] = None,
        parent_msg_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> "Envelope":
        """Construct a fresh envelope with a new ULID and current timestamp."""
        if isinstance(payload, BaseModel):
            payload_dict = payload.model_dump(exclude_none=True)
        else:
            payload_dict = payload
        return cls(
            msg_id=_ulid_str_or_raise(),
            type=type,
            agent_id=agent_id,
            session_id=session_id,
            task_id=task_id,
            parent_msg_id=parent_msg_id,
            timestamp_ms=int(time.time() * 1000),
            payload=payload_dict,
            tenant_id=tenant_id,
        )


# ---------------------------------------------------------------------------
# Backend capabilities (for agent registration)
# ---------------------------------------------------------------------------
class BackendCapabilities(BaseModel):
    backend_id: str
    tier: Literal["native", "local_api", "hosted"]
    supports_midstream_inject: bool
    supports_partial_preservation: bool = False
    is_reasoning_model: bool = False
    prompt_cache_available: bool = False
    avg_overhead_per_signal: float = Field(ge=1.0, default=1.0)
    multi_tenant_isolation: Literal["process", "request_id", "none"] = "process"
    model_id: Optional[str] = None


class AgentRegistration(BaseModel):
    agent_id: str
    session_id: str
    tenant_id: Optional[str] = None
    subscribes: list[str] = Field(default_factory=list)
    scopes_owned: list[str] = Field(default_factory=list)
    capabilities: BackendCapabilities


# Type tag → payload model. Used by the router to validate per-type.
PAYLOAD_BY_TYPE: dict[MessageType, type[BaseModel]] = {
    MessageType.THOUGHT: Thought,
    MessageType.INTENTION: Intention,
    MessageType.PIVOT: Pivot,
    MessageType.BELIEF: Belief,
    MessageType.BLOCK: Block,
    MessageType.CONFLICT: Conflict,
    MessageType.RESOLUTION: Resolution,
    MessageType.COST_REPORT: CostReport,
}
