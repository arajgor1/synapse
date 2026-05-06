"""Inference adapters. v1 ships Mock for the conflict demo; real backends in Phase 2+."""

from synapse.adapters.base import (
    BackendUnavailable,
    InferenceAdapter,
    StreamHandle,
    Token,
    UnsupportedCapability,
)
from synapse.adapters.mock import MockAdapter

__all__ = [
    "InferenceAdapter",
    "StreamHandle",
    "Token",
    "BackendUnavailable",
    "UnsupportedCapability",
    "MockAdapter",
]
