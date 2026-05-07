"""OpenInference / OTel trace importer.

OpenInference is a vendor-neutral standard layered on OpenTelemetry that
standardizes tool-call span attributes (input/output/name/agent_id).
Supported frameworks: LangChain, LlamaIndex, OpenAI SDK, Anthropic SDK,
AutoGen, and growing.

This importer accepts two shapes:

1. **OTel/OTLP JSON export**: ``{"resourceSpans": [{"scopeSpans": [{"spans": [...]}]}]}``
2. **Flat span list**: ``[{...span...}, {...span...}]`` (the simpler shape Phoenix and other tools sometimes export)

Span attributes used:
  - ``openinference.span.kind`` — filter for "TOOL" / "AGENT" / "CHAIN"
  - ``tool.name`` / ``tool_call.name`` — the tool being invoked
  - ``input.value`` / ``tool.args`` — tool arguments (JSON string or dict)
  - ``output.value`` / ``tool.result`` — tool output
  - ``agent.id`` / ``session.id`` — multi-agent attribution
  - ``trace_id``, ``span_id``, ``parent_span_id`` — top-level span fields
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from ..events import AuditEvent


def import_openinference(path: str) -> Iterable[AuditEvent]:
    text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text)
    spans = list(_iter_spans(data))
    for span in spans:
        ev = _span_to_event(span)
        if ev is not None:
            yield ev


def _iter_spans(data: Any) -> Iterable[dict]:
    """Yield individual spans from any of the supported envelope shapes."""
    if isinstance(data, list):
        for item in data:
            yield from _iter_spans(item)
        return

    if not isinstance(data, dict):
        return

    if "spans" in data and isinstance(data["spans"], list):
        for s in data["spans"]:
            yield s
        return

    if "resourceSpans" in data:
        for rs in data.get("resourceSpans", []):
            for ss in rs.get("scopeSpans", []):
                for s in ss.get("spans", []):
                    yield s
        return

    # If it looks like a single span itself
    if "name" in data and ("attributes" in data or "spanId" in data or "span_id" in data):
        yield data


def _attrs_to_dict(attrs) -> dict[str, Any]:
    """OpenInference attrs come in two shapes:
       - dict (flat key/value)
       - list of {"key": ..., "value": {"stringValue"|"intValue"|...}}
    """
    if isinstance(attrs, dict):
        return attrs
    if isinstance(attrs, list):
        out: dict[str, Any] = {}
        for kv in attrs:
            k = kv.get("key")
            v = kv.get("value", {})
            if isinstance(v, dict):
                # OTel's value-of-many-types
                for typed_key in (
                    "stringValue", "intValue", "doubleValue", "boolValue",
                    "string_value", "int_value", "double_value", "bool_value",
                ):
                    if typed_key in v:
                        out[k] = v[typed_key]
                        break
                else:
                    if "arrayValue" in v:
                        out[k] = v["arrayValue"].get("values", [])
                    else:
                        out[k] = v
            else:
                out[k] = v
        return out
    return {}


def _ts_to_ms(value) -> int:
    """OTel uses unix nanoseconds (int) or ISO-8601 string."""
    if isinstance(value, (int, float)):
        # Heuristic: > 1e15 means nanoseconds, > 1e12 means ms
        if value > 1e15:
            return int(value / 1_000_000)
        if value > 1e12:
            return int(value)
        return int(value * 1000)
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            pass
    return 0


def _maybe_parse_json(value) -> Any:
    """Attribute values are often JSON-encoded strings."""
    if isinstance(value, str) and value.strip().startswith(("{", "[")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _span_to_event(span: dict) -> AuditEvent | None:
    attrs = _attrs_to_dict(span.get("attributes", {}))

    # Filter: only consider tool-call spans
    span_kind = (
        attrs.get("openinference.span.kind")
        or attrs.get("span.kind")
        or span.get("kind")
        or ""
    ).upper()
    # OpenInference standard kinds: LLM, CHAIN, RETRIEVER, EMBEDDING, AGENT, TOOL
    # We want TOOL spans (and AGENT delegations) since those are what mutate state
    if span_kind and span_kind not in {"TOOL", "AGENT", "CHAIN"}:
        return None

    tool_name = (
        attrs.get("tool.name")
        or attrs.get("tool_call.name")
        or attrs.get("name")
        or span.get("name")
    )
    if not tool_name:
        return None

    tool_args = (
        _maybe_parse_json(attrs.get("input.value"))
        or _maybe_parse_json(attrs.get("tool.args"))
        or _maybe_parse_json(attrs.get("tool_call.arguments"))
        or {}
    )
    if not isinstance(tool_args, dict):
        tool_args = {"_raw_input": tool_args}

    tool_result = (
        _maybe_parse_json(attrs.get("output.value"))
        or _maybe_parse_json(attrs.get("tool.result"))
        or None
    )

    agent_id = (
        attrs.get("agent.id")
        or attrs.get("openinference.agent.id")
        or attrs.get("graph.node.id")
        or "unknown_agent"
    )
    session_id = (
        attrs.get("session.id")
        or attrs.get("session_id")
        or span.get("traceId")
        or span.get("trace_id")
        or "unknown_session"
    )

    trace_id = span.get("traceId") or span.get("trace_id") or str(session_id)
    span_id = span.get("spanId") or span.get("span_id") or attrs.get("span_id") or ""
    parent_span_id = span.get("parentSpanId") or span.get("parent_span_id")

    ts_start = _ts_to_ms(
        span.get("startTimeUnixNano")
        or span.get("start_time")
        or span.get("startTime")
        or 0
    )
    ts_end = _ts_to_ms(
        span.get("endTimeUnixNano")
        or span.get("end_time")
        or span.get("endTime")
        or 0
    )
    if ts_end == 0:
        ts_end = ts_start

    status_obj = span.get("status") or {}
    if isinstance(status_obj, dict):
        status = "error" if status_obj.get("code") == 2 or status_obj.get("code") == "ERROR" else "ok"
    else:
        status = "ok"

    return AuditEvent(
        trace_id=str(trace_id),
        span_id=str(span_id) or f"{agent_id}_{ts_start}",
        parent_span_id=parent_span_id,
        agent_id=str(agent_id),
        session_id=str(session_id),
        tool_name=str(tool_name),
        tool_args=tool_args,
        tool_result=tool_result,
        status=status,
        ts_start_ms=ts_start,
        ts_end_ms=ts_end,
        raw=span,
    )
