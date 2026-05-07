"""Generic JSONL importer.

Each line is a JSON object representing one tool call. The schema is
intentionally permissive so any agent framework can dump tool-call
events as JSONL with minimal effort.

Required fields per record:
  - agent_id (str)
  - session_id (str)
  - tool_name (str)
  - ts_start_ms (int) OR timestamp (ISO-8601 str)

Optional:
  - trace_id, span_id, parent_span_id, ts_end_ms, tool_args (dict),
    tool_result (any), status, state_diff
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterable

from ..events import AuditEvent


def _parse_ts(value) -> int:
    """Coerce a timestamp into ms-since-epoch."""
    if isinstance(value, (int, float)):
        # Already ms or s? Heuristic: > 1e12 means ms, otherwise s
        return int(value if value > 1e12 else value * 1000)
    if isinstance(value, str):
        # ISO-8601
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            pass
    return 0


def import_jsonl(path: str) -> Iterable[AuditEvent]:
    """Yield AuditEvent records from a JSONL file."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{lineno}: invalid JSON: {e}")
            yield _record_to_event(rec, fallback_id=f"{p.stem}_{lineno}")


def _record_to_event(rec: dict, fallback_id: str) -> AuditEvent:
    # Required fields
    agent_id = rec.get("agent_id") or rec.get("agent") or "unknown_agent"
    session_id = rec.get("session_id") or rec.get("session") or "unknown_session"
    tool_name = rec.get("tool_name") or rec.get("tool") or rec.get("name") or "unknown_tool"

    # Timestamps
    ts_start = _parse_ts(rec.get("ts_start_ms") or rec.get("timestamp") or rec.get("start_time"))
    ts_end = _parse_ts(rec.get("ts_end_ms") or rec.get("end_time")) or ts_start

    return AuditEvent(
        trace_id=rec.get("trace_id") or session_id,
        span_id=rec.get("span_id") or fallback_id,
        parent_span_id=rec.get("parent_span_id"),
        agent_id=str(agent_id),
        session_id=str(session_id),
        tool_name=str(tool_name),
        tool_args=dict(rec.get("tool_args") or rec.get("args") or rec.get("inputs") or {}),
        tool_result=rec.get("tool_result") or rec.get("result") or rec.get("outputs"),
        status=rec.get("status", "ok"),
        ts_start_ms=ts_start,
        ts_end_ms=ts_end,
        state_diff=rec.get("state_diff"),
        raw=rec,
    )
