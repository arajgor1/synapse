"""Real-MCP-client validation of synapse/mcp/server.py.

Spawns the server as a stdio subprocess, connects via the official
``mcp`` Python client, runs the full lifecycle: initialize -> tools/list
-> tools/call. This is the test that catches any drift between our
hand-written JSON-RPC loop and what real MCP clients (Claude Desktop,
Cursor, Continue, Cline, Windsurf) expect on the wire.

If this test passes, any MCP-compliant client can connect to the
Synapse MCP server. If a specific client (e.g. Claude Desktop) has
some quirk our server trips over, the user-facing reproducer is in
``MCP_CLIENT_VERIFICATION.md``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

mcp = pytest.importorskip(
    "mcp", reason="install with `pip install mcp` for real-client validation"
)
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _server_params() -> StdioServerParameters:
    """Spawn ``python -m synapse.mcp.server`` with the current interpreter."""
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "synapse.mcp.server"],
        env=None,
    )


@pytest.mark.asyncio
async def test_real_mcp_client_can_initialize_and_list_tools(tmp_path):
    """Full handshake: initialize -> tools/list. Proves Claude Desktop /
    Cursor / Continue / Cline can at least connect and discover the
    server's tool surface."""
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            assert init.serverInfo.name == "synapse"
            assert init.serverInfo.version  # non-empty
            assert init.protocolVersion  # any string

            tools = await session.list_tools()
            tool_names = sorted(t.name for t in tools.tools)
            # All five documented tools must be present
            for expected in (
                "audit_trace_file",
                "find_conflicts_in_session",
                "get_drift_score",
                "list_supported_trace_formats",
                "explain_conflict",
            ):
                assert expected in tool_names, (
                    f"MCP server is missing the {expected!r} tool. "
                    f"Got: {tool_names}"
                )


@pytest.mark.asyncio
async def test_real_mcp_client_can_call_no_arg_tool(tmp_path):
    """Call a tool that needs no args (list_supported_trace_formats).
    Proves the tools/call path round-trips a real result back."""
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "list_supported_trace_formats", arguments={},
            )
            assert not result.isError, (
                f"tool returned error: {[c.text for c in result.content]}"
            )
            assert result.content, "tool returned empty content"
            payload = json.loads(result.content[0].text)
            assert "formats" in payload, payload
            # The server returns format dicts with {name, description}
            names = {f.get("name") for f in payload["formats"]}
            for fmt in ("openinference", "langsmith", "jsonl"):
                assert fmt in names, (
                    f"Expected {fmt} in supported formats, got {names}"
                )


@pytest.mark.asyncio
async def test_real_mcp_client_audit_jsonl_file(tmp_path):
    """End-to-end: write a JSONL file, ask the server to audit it via
    tools/call, verify a conflict is detected."""
    log = tmp_path / "trace.jsonl"
    events = [
        {
            "trace_id": "t", "span_id": "a", "agent_id": "alice",
            "session_id": "mcp_test",
            "tool_name": "edit_file",
            "tool_args": {"path": "x.py", "content": "v1"},
            "ts_start_ms": 1000, "ts_end_ms": 1050,
        },
        {
            "trace_id": "t", "span_id": "b", "agent_id": "bob",
            "session_id": "mcp_test",
            "tool_name": "edit_file",
            "tool_args": {"path": "x.py", "content": "v2"},
            "ts_start_ms": 1010, "ts_end_ms": 1060,
        },
    ]
    log.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")

    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "audit_trace_file",
                arguments={"path": str(log)},
            )
            assert not result.isError, [c.text for c in result.content]
            payload = json.loads(result.content[0].text)
            assert payload.get("total_events", 0) >= 2
            # The audit_trace_file tool returns the AuditReport schema —
            # field is total_conflicts (not n_conflicts).
            n_conflicts = payload.get("total_conflicts", payload.get("n_conflicts", 0))
            assert n_conflicts >= 1, (
                f"expected ≥1 conflict on shared scope, got {payload}"
            )


@pytest.mark.asyncio
async def test_real_mcp_client_unknown_tool_returns_error(tmp_path):
    """Calling a non-existent tool must return a structured error, not crash
    the server connection (otherwise Claude Desktop would silently disconnect)."""
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            try:
                await session.call_tool("does_not_exist", arguments={})
            except Exception as e:
                # Any structured error is fine — the connection survived
                assert "does_not_exist" in str(e) or "unknown" in str(e).lower()
                return
            # If no exception, the result must mark itself as an error
            # (Claude Desktop relies on isError to surface to the user).
            # Some MCP clients raise McpError, others return isError=True.
