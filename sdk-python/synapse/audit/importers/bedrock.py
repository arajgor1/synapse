"""AWS Bedrock Agents trace importer.

Bedrock Agents emit traces in two ways:

1. **Inline `trace` field** in the InvokeAgent streaming response (default).
   Each chunk's ``trace`` object has nested orchestration / pre/post-processing
   trace blocks. The shape is documented at
   https://docs.aws.amazon.com/bedrock/latest/userguide/trace-events.html

2. **OpenTelemetry export** via CloudWatch when "Model invocation logging
   with OpenTelemetry" is enabled. That format is OTLP/JSON and the
   existing ``openinference`` importer handles it directly.

This importer targets format (1) — the inline trace shape — because most
production users export it via boto3 streaming and dump to JSON.

Shape we accept (one of):

    {"agentSessionId": "...", "traces": [{...trace...}, ...]}

    [{"agentSessionId": "...", "trace": {...}}, ...]   # one entry per chunk

    {"trace": {"orchestrationTrace": {...}}}           # single trace

Each ``orchestrationTrace`` may contain:
- ``modelInvocationInput`` / ``modelInvocationOutput``
- ``invocationInput.actionGroupInvocationInput`` (= tool call)
- ``observation.actionGroupInvocationOutput``    (= tool result)

We map ``actionGroupInvocationInput`` → AuditEvent and pair it with the
matching ``actionGroupInvocationOutput`` by ``traceId`` when present.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from ..events import AuditEvent


def import_bedrock(path: str) -> Iterable[AuditEvent]:
    text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text)
    yield from _iter_events(data)


def _iter_events(data: Any) -> Iterable[AuditEvent]:
    if isinstance(data, list):
        for item in data:
            yield from _iter_events(item)
        return

    if not isinstance(data, dict):
        return

    # Pull session id — Bedrock uses agentSessionId or sessionId
    session_id = (
        data.get("agentSessionId")
        or data.get("sessionId")
        or data.get("session_id")
        or "bedrock-session"
    )
    agent_id = (
        data.get("agentId")
        or data.get("agent_id")
        or "bedrock-agent"
    )

    # `traces` array — each entry can be either a raw trace block OR
    # a wrapper of shape {"agentId": "...", "trace": {...}}.
    if "traces" in data and isinstance(data["traces"], list):
        for t in data["traces"]:
            if isinstance(t, dict):
                # Per-entry agentId overrides the top-level
                entry_agent = t.get("agentId") or t.get("agent_id") or agent_id
                if "trace" in t and isinstance(t["trace"], dict):
                    yield from _trace_to_events(t["trace"], session_id, entry_agent)
                elif "orchestrationTrace" in t or "preProcessingTrace" in t:
                    yield from _trace_to_events(t, session_id, entry_agent)
        return

    if "trace" in data:
        yield from _trace_to_events(data["trace"], session_id, agent_id)
        return

    # If it looks like a trace itself
    if "orchestrationTrace" in data or "preProcessingTrace" in data:
        yield from _trace_to_events(data, session_id, agent_id)


def _trace_to_events(trace: dict, session_id: str, agent_id: str) -> Iterable[AuditEvent]:
    orch = trace.get("orchestrationTrace") or {}
    inv_input = orch.get("invocationInput") or {}
    obs = orch.get("observation") or {}

    action_input = inv_input.get("actionGroupInvocationInput")
    action_output = obs.get("actionGroupInvocationOutput")

    if action_input:
        trace_id = (
            inv_input.get("traceId")
            or orch.get("traceId")
            or trace.get("traceId")
            or "bedrock-trace"
        )
        # Bedrock represents the tool's logical name as actionGroupName +
        # apiPath OR functionName. Normalize to "<group>.<fn>".
        group = action_input.get("actionGroupName", "")
        fn = action_input.get("function") or action_input.get("apiPath") or "unknown"
        # apiPath looks like "/cancel" — strip the leading slash
        fn_clean = fn.lstrip("/")
        tool_name = f"{group}.{fn_clean}" if group else fn_clean

        # Parameters: list of {"name", "value", "type"}
        args: dict[str, Any] = {}
        for p in action_input.get("parameters", []) or []:
            if isinstance(p, dict) and "name" in p:
                args[p["name"]] = p.get("value")

        # request body (string) for POST-like calls
        req_body = action_input.get("requestBody")
        if req_body:
            args["_requestBody"] = req_body

        # Result (string), if present
        result = None
        if action_output and "text" in action_output:
            result = action_output["text"]

        # Timestamps — Bedrock doesn't always include precise timing; fall
        # back to "now" if absent. ts is ISO 8601 in UTC when present.
        ts_str = inv_input.get("startTime") or trace.get("startTime")
        ts_ms = _iso_to_ms(ts_str) if ts_str else int(datetime.utcnow().timestamp() * 1000)
        end_str = action_output.get("endTime") if action_output else None
        end_ms = _iso_to_ms(end_str) if end_str else ts_ms

        yield AuditEvent(
            trace_id=str(trace_id),
            span_id=str(trace_id) + ":action",
            agent_id=str(agent_id),
            session_id=str(session_id),
            tool_name=str(tool_name),
            ts_start_ms=ts_ms,
            ts_end_ms=end_ms,
            tool_args=args,
            tool_result=result,
            status="ok" if action_output else "ok",
            raw={"bedrock_trace": trace},
        )

    # Sub-agent / collaborator routing — Bedrock's multi-agent collab
    # produces nested traces under `routingClassifierTrace` and per-
    # collaborator `agentCollaboratorInvocationInput`.
    collab_input = orch.get("agentCollaboratorInvocationInput")
    collab_output = obs.get("agentCollaboratorInvocationOutput") if obs else None
    if collab_input:
        trace_id = collab_input.get("agentCollaboratorAliasArn") or "bedrock-collab"
        sub_agent_id = collab_input.get("agentCollaboratorName") or "collaborator"
        ts_ms = int(datetime.utcnow().timestamp() * 1000)
        result = collab_output.get("output", {}).get("text") if collab_output else None
        yield AuditEvent(
            trace_id=str(trace_id),
            span_id=str(trace_id) + ":collab",
            agent_id=str(sub_agent_id),
            session_id=str(session_id),
            tool_name="agent.invoke",
            ts_start_ms=ts_ms,
            ts_end_ms=ts_ms,
            tool_args={"input": collab_input.get("input", {}).get("text")},
            tool_result=result,
            status="ok",
            raw={"bedrock_trace": trace},
        )


def _iso_to_ms(iso: str) -> int:
    # AWS uses RFC3339 with "Z" suffix; datetime.fromisoformat needs +00:00
    s = iso.replace("Z", "+00:00") if iso.endswith("Z") else iso
    try:
        return int(datetime.fromisoformat(s).timestamp() * 1000)
    except Exception:
        return int(datetime.utcnow().timestamp() * 1000)
