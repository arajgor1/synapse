"""Azure AI Agent Service / Application Insights trace importer.

Azure AI Agent Service (under Azure AI Foundry) emits agent telemetry
to Application Insights. Tool calls land as either:

  - **Dependency** records (most tool invocations)
  - **CustomEvent** records (agent step boundaries)

App Insights export shape (from Log Analytics or the REST API):

    {"value": [{...row...}, ...]}        # standard query response

Each row has `customDimensions` (a dict of agent-specific keys):

  - ``ai.agent.id`` / ``ai_agent_id``        agent identity
  - ``ai.agent.run_id``                      session id
  - ``ai.tool.name``                         tool name
  - ``ai.tool.input`` / ``ai.tool.arguments``
  - ``ai.tool.output``
  - ``operation_Id``                         trace id (top-level field)
  - ``id``                                   span id (top-level field)

Some users also export via OpenTelemetry → Azure Monitor exporter, which
produces the OTel envelope handled by the openinference importer.

This importer targets the App Insights query export shape.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from ..events import AuditEvent


def import_azure(path: str) -> Iterable[AuditEvent]:
    text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text)
    rows = list(_iter_rows(data))
    for row in rows:
        ev = _row_to_event(row)
        if ev is not None:
            yield ev


def _iter_rows(data: Any) -> Iterable[dict]:
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                yield item
            else:
                yield from _iter_rows(item)
        return
    if isinstance(data, dict):
        if "value" in data and isinstance(data["value"], list):
            for r in data["value"]:
                yield r
            return
        if "tables" in data:
            # Direct Log Analytics tabular shape
            for tbl in data["tables"]:
                cols = [c["name"] for c in tbl.get("columns", [])]
                for row in tbl.get("rows", []):
                    yield dict(zip(cols, row))
            return
        # Looks like a single row
        if any(k in data for k in ("operation_Id", "name", "customDimensions")):
            yield data


def _custom_dims(row: dict) -> dict[str, Any]:
    cd = row.get("customDimensions") or row.get("custom_dimensions") or {}
    if isinstance(cd, str):
        try:
            cd = json.loads(cd)
        except Exception:
            cd = {}
    return cd if isinstance(cd, dict) else {}


def _row_to_event(row: dict) -> AuditEvent | None:
    cd = _custom_dims(row)

    # Filter to tool-call-shaped records. Dependency type "AGENT_TOOL"
    # is the convention used by Azure AI samples; some users use plain
    # "InProc" with an ai.tool.name dimension.
    dep_type = row.get("type") or row.get("itemType")
    has_tool_attr = (
        "ai.tool.name" in cd
        or "ai_tool_name" in cd
        or "tool.name" in cd
    )
    if not has_tool_attr and dep_type not in ("AGENT_TOOL", "Tool"):
        return None

    tool_name = (
        cd.get("ai.tool.name")
        or cd.get("ai_tool_name")
        or cd.get("tool.name")
        or row.get("name")
        or "unknown_tool"
    )

    args_raw = (
        cd.get("ai.tool.input")
        or cd.get("ai.tool.arguments")
        or cd.get("ai_tool_input")
        or "{}"
    )
    if isinstance(args_raw, str):
        try:
            args = json.loads(args_raw)
        except Exception:
            args = {"_raw": args_raw}
    else:
        args = args_raw if isinstance(args_raw, dict) else {"_raw": str(args_raw)}

    result = cd.get("ai.tool.output") or cd.get("ai_tool_output")

    agent_id = (
        cd.get("ai.agent.id")
        or cd.get("ai_agent_id")
        or row.get("cloud_RoleName")
        or "azure-agent"
    )
    # NOTE: do NOT fall back to operation_ParentId — that's a span id,
    # not a session. Falling back to the trace id (operation_Id) is the
    # least-bad default for orphan rows.
    session_id = (
        cd.get("ai.agent.run_id")
        or cd.get("ai_agent_run_id")
        or row.get("session_Id")
        or row.get("operation_Id")
        or "azure-session"
    )

    trace_id = row.get("operation_Id") or row.get("operation_id") or "azure-trace"
    span_id = row.get("id") or trace_id + ":" + str(tool_name)
    parent_span_id = row.get("operation_ParentId") or row.get("operation_parent_id")

    ts_start_ms = _ts_to_ms(row.get("timestamp") or row.get("start"))
    duration_ms = row.get("duration") or row.get("durationMs") or 0
    try:
        ts_end_ms = ts_start_ms + int(float(duration_ms))
    except (TypeError, ValueError):
        ts_end_ms = ts_start_ms

    return AuditEvent(
        trace_id=str(trace_id),
        span_id=str(span_id),
        agent_id=str(agent_id),
        session_id=str(session_id),
        tool_name=str(tool_name),
        ts_start_ms=ts_start_ms,
        ts_end_ms=ts_end_ms,
        parent_span_id=parent_span_id,
        tool_args=args,
        tool_result=result,
        status="ok" if (row.get("success") in (True, "True", "true", 1, None)) else "error",
        raw={"azure_row": row},
    )


def _ts_to_ms(ts: Any) -> int:
    if ts is None:
        return int(datetime.utcnow().timestamp() * 1000)
    if isinstance(ts, (int, float)):
        # ms since epoch if it's already a number
        return int(ts)
    if isinstance(ts, str):
        s = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        try:
            return int(datetime.fromisoformat(s).timestamp() * 1000)
        except Exception:
            pass
    return int(datetime.utcnow().timestamp() * 1000)
