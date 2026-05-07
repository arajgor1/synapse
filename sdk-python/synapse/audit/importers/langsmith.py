"""LangSmith trace export importer.

LangSmith exports come as a JSON array of `Run` records (one per
LLM call, chain step, or tool call). The interesting ones for us are
`run_type == "tool"`. We also synthesize tool-call events from
`run_type == "chain"` records when their name matches a known tool.

LangSmith schema (the bits we care about):
  - id (UUID, treat as span_id)
  - trace_id, parent_run_id
  - run_type ("llm" | "chain" | "tool" | "retriever")
  - name (chain/tool name)
  - inputs (dict)
  - outputs (dict)
  - start_time, end_time (ISO-8601)
  - extra.metadata: agent_id, session_id, ls_provider, ls_model_name
  - status ("success" | "error")

Multi-agent attribution: LangSmith propagates agent identity via the
``extra.metadata.agent_name`` (LangGraph) or ``extra.metadata.agent_id``
keys. If neither is set, we fall back to the parent chain's name.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from ..events import AuditEvent


def import_langsmith(path: str) -> Iterable[AuditEvent]:
    text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text)
    runs = list(_iter_runs(data))
    by_id: dict[str, dict] = {r.get("id"): r for r in runs if r.get("id")}

    for run in runs:
        if run.get("run_type") != "tool":
            continue
        ev = _run_to_event(run, by_id)
        if ev is not None:
            yield ev


def _iter_runs(data: Any) -> Iterable[dict]:
    if isinstance(data, list):
        for r in data:
            if isinstance(r, dict):
                yield r
    elif isinstance(data, dict):
        if "runs" in data and isinstance(data["runs"], list):
            yield from _iter_runs(data["runs"])
        elif "session" in data and "runs" in data:
            yield from _iter_runs(data["runs"])
        else:
            yield data


def _ts_to_ms(value) -> int:
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            return 0
    if isinstance(value, (int, float)):
        return int(value if value > 1e12 else value * 1000)
    return 0


def _agent_id_from_run(run: dict, by_id: dict[str, dict]) -> str:
    """Resolve agent identity by walking up parent chain."""
    extra = run.get("extra") or {}
    meta = extra.get("metadata") or {}

    for k in ("agent_id", "agent_name", "graph.node.id", "ls_agent_id"):
        if meta.get(k):
            return str(meta[k])

    # Walk up parent_run_id chain looking for a chain run with an agent label
    cursor = run.get("parent_run_id")
    visited = set()
    while cursor and cursor not in visited:
        visited.add(cursor)
        parent = by_id.get(cursor)
        if not parent:
            break
        p_meta = (parent.get("extra") or {}).get("metadata") or {}
        for k in ("agent_id", "agent_name", "graph.node.id"):
            if p_meta.get(k):
                return str(p_meta[k])
        if parent.get("run_type") == "chain" and parent.get("name"):
            return str(parent["name"])  # last-resort fallback
        cursor = parent.get("parent_run_id")

    return "unknown_agent"


def _run_to_event(run: dict, by_id: dict[str, dict]) -> AuditEvent | None:
    inputs = run.get("inputs") or {}
    outputs = run.get("outputs") or {}
    extra = run.get("extra") or {}
    meta = extra.get("metadata") or {}

    tool_name = run.get("name") or run.get("tool_name") or "unknown_tool"
    agent_id = _agent_id_from_run(run, by_id)
    session_id = (
        meta.get("session_id")
        or meta.get("thread_id")
        or extra.get("session_id")
        or run.get("session_id")
        or run.get("trace_id")
        or "unknown_session"
    )

    # LangSmith inputs are usually `{"args": [...], "kwargs": {...}}` or
    # the actual tool args directly. Try to flatten.
    if "args" in inputs and "kwargs" in inputs:
        tool_args = dict(inputs.get("kwargs") or {})
        a = inputs.get("args") or []
        if isinstance(a, list) and a and isinstance(a[0], dict):
            tool_args.update(a[0])
    else:
        tool_args = dict(inputs)

    status_str = run.get("status") or run.get("error") or "success"
    status = "error" if status_str in ("error", "failed") or run.get("error") else "ok"

    return AuditEvent(
        trace_id=str(run.get("trace_id") or session_id),
        span_id=str(run.get("id") or f"{agent_id}_{tool_name}"),
        parent_span_id=run.get("parent_run_id"),
        agent_id=str(agent_id),
        session_id=str(session_id),
        tool_name=str(tool_name),
        tool_args=tool_args,
        tool_result=outputs,
        status=status,
        ts_start_ms=_ts_to_ms(run.get("start_time")),
        ts_end_ms=_ts_to_ms(run.get("end_time")),
        raw=run,
    )
