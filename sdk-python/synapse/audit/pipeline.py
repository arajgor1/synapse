"""End-to-end audit pipeline: trace -> events -> scope -> conflicts -> report.

The single entry point used by the CLI and by anyone calling
``synapse.audit.audit_traces(path)`` programmatically.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .events import AuditEvent, is_write
from .scope_inference import annotate_events
from .conflict_detector import detect_conflicts
from .drift import compute_sas
from .report import AuditReport
from .importers import auto_import


# Rough cost per 1k input tokens for the most common Haiku-class models.
# Used only for the "estimated wasted dollars" figure on the audit report.
_AVG_HAIKU_USD_PER_KTOK = 0.001


def _events_from_path(path: str | Path) -> list[AuditEvent]:
    return list(auto_import(str(path)))


def audit_traces(
    path: str | Path,
    *,
    lookback_ms: int = 24 * 60 * 60 * 1000,  # 24h — production traces span hours
    write_only: bool = True,
) -> AuditReport:
    """Run the audit pipeline and return an AuditReport.

    Args:
        path: trace file (.json, .jsonl, .ndjson). Auto-detects format.
        lookback_ms: stale-base-overwrite window. Default 24h for audit
            mode (production trace exports often span hours/days). Live
            mode uses a much tighter window (60s) — see runtime/router.
        write_only: only consider write-class tool calls. Default True.

    Returns:
        AuditReport — call .write_html(), .write_json(), or .print_summary().
    """
    events = _events_from_path(path)
    annotate_events(events)

    sessions: dict[str, list[str]] = {}
    write_count = 0
    for ev in events:
        sessions.setdefault(ev.session_id, []).append(ev.agent_id)
        if is_write(ev):
            write_count += 1

    conflicts = detect_conflicts(events, lookback_ms=lookback_ms, write_only=write_only)

    # Cost estimate: each conflict roughly wasted the LLM tokens that
    # produced the soon-to-be-clobbered work. We don't know the actual
    # token counts unless they're in `raw`, so use a per-event default.
    def _tokens_for(ev: AuditEvent) -> int:
        raw = ev.raw or {}
        # Try common attribute paths
        for k in ("output_tokens", "usage.output_tokens", "tokens_out"):
            if k in raw:
                return int(raw[k])
        # OpenInference usage attribute
        attrs = raw.get("attributes")
        if isinstance(attrs, dict):
            for k in ("llm.token_count.completion", "llm.tokens.output"):
                if k in attrs:
                    return int(attrs[k])
        return 200  # conservative default

    wasted_tokens = 0
    for c in conflicts:
        # Each colliding prior write contributed tokens that get clobbered
        for prior in c.conflicting:
            wasted_tokens += _tokens_for(prior)

    # SCF drift score: per-agent-pair Semantic Alignment Score.
    # Cheap pure-Python pass; flags soft drift even when no hard CONFLICT
    # fired. Free (no LLM, no I/O) so always on.
    sas_pairs = compute_sas(events)

    return AuditReport(
        source_path=str(path),
        total_events=len(events),
        total_write_events=write_count,
        sessions=sessions,
        conflicts=conflicts,
        estimated_wasted_tokens=wasted_tokens,
        estimated_wasted_usd=(wasted_tokens / 1000) * _AVG_HAIKU_USD_PER_KTOK,
        sas_pairs=sas_pairs,
    )
