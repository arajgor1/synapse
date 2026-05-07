"""Normalized audit-event schema.

All trace formats (OpenInference OTel, LangSmith, generic JSONL) are
normalized into AuditEvent records so downstream stages (scope inference,
conflict detection, report generation) are format-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class AuditEvent:
    """One tool-call observation extracted from a trace.

    Mirrors the minimal shape of an OpenInference tool-call span. Other
    formats (LangSmith run records, raw JSONL events) get translated
    into this shape by their importer.

    Fields are intentionally narrow — we only carry what the conflict
    detector needs. The original trace payload is kept under `raw` for
    round-tripping and debugging.
    """

    # Identifiers — every importer must populate these
    trace_id: str
    span_id: str
    agent_id: str
    session_id: str
    tool_name: str

    # Timing (milliseconds since epoch)
    ts_start_ms: int
    ts_end_ms: int

    # Optional structural data
    parent_span_id: Optional[str] = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    tool_result: Optional[Any] = None
    status: str = "ok"  # "ok" | "error"

    # Filled by scope_inference.infer_scope
    scope_inferred: list[str] = field(default_factory=list)

    # Optional state diff (pulled from RESOLUTION-style events)
    state_diff: Optional[dict[str, Any]] = None

    # Original trace payload, for inspection / round-trip
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_write(event: AuditEvent) -> bool:
    """Heuristic: does this tool call mutate state?

    Used to filter audits to write-class operations, since read-only
    tool calls (search, fetch, retrieve) cannot collide.
    """
    name = event.tool_name.lower()
    write_kws = (
        "write", "edit", "patch", "delete", "create", "update", "modify",
        "execute", "run", "send", "post", "publish", "deploy", "commit",
        "save", "insert", "upsert", "merge", "render", "generate",
    )
    if any(kw in name for kw in write_kws):
        return True
    # Path / file_path arg is a strong write hint for filesystem tools
    if "path" in event.tool_args or "file_path" in event.tool_args:
        # Read tools usually have "read" in the name; assume write otherwise
        if "read" not in name and "search" not in name and "list" not in name:
            return True
    return False
