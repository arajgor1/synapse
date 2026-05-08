"""GCP Vertex AI Agent Builder / ADK trace importer.

Vertex AI Agent Builder (Reasoning Engine) and the open-source Agent
Development Kit (ADK) export traces via Google Cloud Trace, which is
OpenTelemetry-compatible. Tool calls land as spans with attribute
keys like:

  - ``gen_ai.operation.name``         "execute_tool"
  - ``gen_ai.tool.name``               the tool name
  - ``gen_ai.agent.name``              agent identity
  - ``gen_ai.system``                  "vertex_ai" / "google_genai"
  - ``gen_ai.request.model``           model id
  - ``gcp.vertex.agent.session_id``    session
  - ``gcp.vertex.agent.input``         JSON-stringified args
  - ``gcp.vertex.agent.output``        JSON-stringified result

The export shape is the standard Cloud Trace JSON:

    {"spans": [{...span...}, ...]}

or the OTLP/JSON envelope used when tracing is mirrored through the
OTel collector (handled by the existing openinference importer).

We accept either:

    {"spans": [{...span...}, ...]}                # Cloud Trace export
    [{...span...}, ...]                            # flat list

If the input has ``resourceSpans`` (OTLP envelope), defer to the
OpenInference importer's logic — same shape.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from ..events import AuditEvent


def import_vertex(path: str) -> Iterable[AuditEvent]:
    text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text)
    spans = list(_iter_spans(data))
    for span in spans:
        ev = _span_to_event(span)
        if ev is not None:
            yield ev


def _iter_spans(data: Any) -> Iterable[dict]:
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and ("name" in item or "displayName" in item):
                yield item
            else:
                yield from _iter_spans(item)
        return
    if not isinstance(data, dict):
        return
    if "spans" in data and isinstance(data["spans"], list):
        for s in data["spans"]:
            yield s
        return
    if "resourceSpans" in data:
        for rs in data["resourceSpans"]:
            for ss in rs.get("scopeSpans", []):
                for s in ss.get("spans", []):
                    yield s
        return


def _attrs(span: dict) -> dict[str, Any]:
    """Cloud Trace exports either flat ``attributes: {k: v}`` or
    ``attributes.attributeMap: {k: {"stringValue": {"value": ...}}}``."""
    a = span.get("attributes")
    if isinstance(a, dict):
        if "attributeMap" in a:
            out = {}
            for k, v in a["attributeMap"].items():
                if isinstance(v, dict):
                    sv = v.get("stringValue") or v.get("intValue") or v.get("boolValue")
                    if isinstance(sv, dict):
                        out[k] = sv.get("value")
                    else:
                        out[k] = sv
                else:
                    out[k] = v
            return out
        return a
    return {}


def _span_to_event(span: dict) -> AuditEvent | None:
    attrs = _attrs(span)

    # Only map tool-execution spans
    op = attrs.get("gen_ai.operation.name") or attrs.get("openinference.span.kind")
    if op and op.lower() not in ("execute_tool", "tool", "tool_call"):
        return None

    tool_name = (
        attrs.get("gen_ai.tool.name")
        or attrs.get("tool.name")
        or attrs.get("name")
        or span.get("name")
        or span.get("displayName", {}).get("value")
        or "unknown_tool"
    )

    # If this isn't clearly a tool span, skip
    if not (attrs.get("gen_ai.tool.name") or attrs.get("tool.name") or op):
        return None

    args_raw = (
        attrs.get("gcp.vertex.agent.input")
        or attrs.get("input.value")
        or attrs.get("tool.args")
        or "{}"
    )
    if isinstance(args_raw, str):
        try:
            args = json.loads(args_raw)
        except Exception:
            args = {"_raw": args_raw}
    else:
        args = args_raw if isinstance(args_raw, dict) else {"_raw": str(args_raw)}

    result = (
        attrs.get("gcp.vertex.agent.output")
        or attrs.get("output.value")
        or attrs.get("tool.result")
    )

    agent_id = (
        attrs.get("gen_ai.agent.name")
        or attrs.get("agent.id")
        or attrs.get("agent.name")
        or "vertex-agent"
    )
    session_id = (
        attrs.get("gcp.vertex.agent.session_id")
        or attrs.get("session.id")
        or "vertex-session"
    )

    # Cloud Trace timing: startTime / endTime as RFC3339 strings or
    # nested {"seconds":..., "nanos":...}
    ts_start_ms = _ts_to_ms(span.get("startTime"))
    ts_end_ms = _ts_to_ms(span.get("endTime")) or ts_start_ms

    trace_id = span.get("traceId") or span.get("trace_id") or "vertex-trace"
    span_id = span.get("spanId") or span.get("span_id") or trace_id + ":" + str(tool_name)

    return AuditEvent(
        trace_id=str(trace_id),
        span_id=str(span_id),
        agent_id=str(agent_id),
        session_id=str(session_id),
        tool_name=str(tool_name),
        ts_start_ms=ts_start_ms,
        ts_end_ms=ts_end_ms,
        parent_span_id=span.get("parentSpanId") or span.get("parent_span_id"),
        tool_args=args,
        tool_result=result,
        status="ok",
        raw={"vertex_span": span},
    )


def _ts_to_ms(ts: Any) -> int:
    if ts is None:
        return int(datetime.utcnow().timestamp() * 1000)
    if isinstance(ts, dict) and "seconds" in ts:
        return int(ts["seconds"]) * 1000 + int(ts.get("nanos", 0)) // 1_000_000
    if isinstance(ts, (int, float)):
        return int(ts)
    if isinstance(ts, str):
        s = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        try:
            return int(datetime.fromisoformat(s).timestamp() * 1000)
        except Exception:
            return int(datetime.utcnow().timestamp() * 1000)
    return int(datetime.utcnow().timestamp() * 1000)
