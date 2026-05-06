"""Synapse — real-time coordination protocol for parallel AI agents.

Pre-alpha. Phase 1 deliverable: end-to-end conflict detection demo with
mocked inference. See the project README for status and roadmap.
"""

from synapse.agent import Agent
from synapse.messages import (
    Belief,
    Block,
    Conflict,
    CostReport,
    Envelope,
    Intention,
    MessageType,
    Pivot,
    Resolution,
    Thought,
)

__version__ = "0.1.0a0"
__all__ = [
    "Agent",
    "Envelope",
    "MessageType",
    "Intention",
    "Conflict",
    "Block",
    "Pivot",
    "Belief",
    "Thought",
    "Resolution",
    "CostReport",
    "__version__",
]
