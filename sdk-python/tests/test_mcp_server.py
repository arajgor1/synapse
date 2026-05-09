"""Tests for the synapse.mcp.server stdio MCP server."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from synapse.mcp import server


@pytest.fixture
def sample_trace(tmp_path: Path) -> str:
    data = {
        "spans": [
            {
                "name": "edit_file",
                "spanId": "sp1",
                "traceId": "tr1",
                "startTime": "2026-05-09T12:00:00Z",
                "endTime": "2026-05-09T12:00:01Z",
                "attributes": {
                    "openinference.span.kind": "TOOL",
                    "tool.name": "edit_file",
                    "tool.args": '{"path": "models.py"}',
                    "agent.id": "alice",
                    "session.id": "s1",
                },
            },
            {
                "name": "edit_file",
                "spanId": "sp2",
                "traceId": "tr1",
                "startTime": "2026-05-09T12:00:02Z",
                "endTime": "2026-05-09T12:00:03Z",
                "attributes": {
                    "openinference.span.kind": "TOOL",
                    "tool.name": "edit_file",
                    "tool.args": '{"path": "models.py"}',
                    "agent.id": "bob",
                    "session.id": "s1",
                },
            },
        ]
    }
    p = tmp_path / "trace.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def test_initialize() -> None:
    resp = server._handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert resp["id"] == 1
    assert resp["result"]["protocolVersion"] == server.PROTOCOL_VERSION
    assert resp["result"]["serverInfo"]["name"] == "synapse"


def test_initialized_is_notification() -> None:
    """`initialized` is a notification — no response expected."""
    resp = server._handle({"jsonrpc": "2.0", "method": "initialized"})
    assert resp is None


def test_tools_list_includes_all_5_tools() -> None:
    resp = server._handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = resp["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == {
        "audit_trace_file",
        "find_conflicts_in_session",
        "get_drift_score",
        "list_supported_trace_formats",
        "explain_conflict",
    }


def test_tool_audit_trace_file(sample_trace: str) -> None:
    resp = server._handle({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "audit_trace_file", "arguments": {"path": sample_trace}},
    })
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["total_events"] == 2
    assert payload["total_conflicts"] == 1
    assert "sas_pairs" in payload
    assert payload["conflict_tiers"] == {"temporal": 1}


def test_tool_explain_conflict(sample_trace: str) -> None:
    # First audit, then explain
    server._handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "audit_trace_file", "arguments": {"path": sample_trace}},
    })
    resp = server._handle({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "explain_conflict", "arguments": {"path": sample_trace, "conflict_index": 0}},
    })
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["conflict_index"] == 0
    assert payload["resolution_tier_hint"] in ("policy", "capability", "temporal", "escalation")
    assert "alice" in payload["explanation"] or "bob" in payload["explanation"]


def test_tool_get_drift_score(sample_trace: str) -> None:
    server._handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "audit_trace_file", "arguments": {"path": sample_trace}},
    })
    resp = server._handle({
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {
            "name": "get_drift_score",
            "arguments": {"path": sample_trace, "agent_a": "alice", "agent_b": "bob"},
        },
    })
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert "matches" in payload
    assert len(payload["matches"]) == 1
    assert payload["matches"][0]["sas"] > 0.5


def test_tool_list_supported_formats() -> None:
    resp = server._handle({
        "jsonrpc": "2.0", "id": 6, "method": "tools/call",
        "params": {"name": "list_supported_trace_formats", "arguments": {}},
    })
    payload = json.loads(resp["result"]["content"][0]["text"])
    names = {f["name"] for f in payload["formats"]}
    assert names == {"openinference", "langsmith", "bedrock", "vertex", "azure", "jsonl"}


def test_unknown_tool_returns_error() -> None:
    resp = server._handle({
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"name": "no_such_tool", "arguments": {}},
    })
    assert "error" in resp
    assert resp["error"]["code"] == -32601


def test_unknown_method_returns_error() -> None:
    resp = server._handle({"jsonrpc": "2.0", "id": 8, "method": "frobnicate"})
    assert "error" in resp
    assert resp["error"]["code"] == -32601


def test_audit_missing_file_returns_error() -> None:
    resp = server._handle({
        "jsonrpc": "2.0", "id": 9, "method": "tools/call",
        "params": {"name": "audit_trace_file", "arguments": {"path": "/nonexistent.json"}},
    })
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert "error" in payload
    assert resp["result"]["isError"] is True
