"""Synapse coordinator — model-agnostic role responsible for:

- Reading the session-wide event stream
- Maintaining a working summary of session state
- Detecting belief divergences across agents
- Routing BLOCK signals to capable peers
- Synthesizing guidance via an LLM when rule-based routing isn't enough

The coordinator is event-driven (not polling): it wakes on BLOCK,
divergence-trigger BELIEF messages, and a periodic background tick.
"""

from runtime.coordinator.belief_divergence import (
    BeliefDivergence,
    detect_divergences,
)

__all__ = ["BeliefDivergence", "detect_divergences"]
