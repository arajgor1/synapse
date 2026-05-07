"""synapse.beliefs — semantic-conflict detection that scope-overlap can't catch.

Two agents can disagree about a domain fact without ever touching the same
file. v0.2 week-5 catches that case via BELIEF emissions + per-emission
divergence detection.

Example: ``data_cleaner`` writes a SQL CTE with ``revenue = qty * price``
and ``analyst`` writes a Python function with ``revenue = qty * price * (1 - discount)``.
Different files. Same semantic disagreement. Synapse spots it because each
agent emitted a BELIEF on the key ``revenue_formula`` with a different value.

Public surface:

    # Manual: caller already knows what facts the agent established
    await synapse.emit_belief(
        agent="cleaner", session=...,
        key="revenue_formula", value="qty * price",
        confidence=0.9, source="observed",
    )

    # Auto-extract from tool results — opt-in
    synapse.install(emit_beliefs_from_tool_results=True)
    # ...now every successful intend() block runs the extractor on its
    # state_diff using your BYO-LLM and emits whatever facts it finds.

    # Inspect divergences for a session
    divs = await synapse.list_divergences(session_id=...)
"""
from __future__ import annotations

from .api import emit_belief, list_divergences, divergences_for_key
from .extractor import extract_beliefs_with_llm, FactExtraction
from .live_detector import detect_live_divergence, LiveDivergenceResult

__all__ = [
    "emit_belief",
    "list_divergences",
    "divergences_for_key",
    "extract_beliefs_with_llm",
    "FactExtraction",
    "detect_live_divergence",
    "LiveDivergenceResult",
]
