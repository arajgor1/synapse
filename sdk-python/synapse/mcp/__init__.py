"""synapse.mcp — Model Context Protocol server for Synapse audit data.

Lets ANY MCP-compatible agent (Claude Desktop, Cursor, custom MCP
clients) query Synapse's audit results as a tool. The server exposes
five tools an agent can call:

  - audit_trace_file(path) -> AuditReport JSON
  - find_conflicts_in_session(session_id) -> list of CONFLICT envelopes
  - get_drift_score(agent_a, agent_b, session_id) -> AgentPairSAS
  - list_supported_trace_formats() -> ["openinference", "langsmith",
                                       "bedrock", "vertex", "azure", "jsonl"]
  - explain_conflict(conflict_id) -> human-readable rationale + tier hint

Run via:
    python -m synapse.mcp.server
or add to Claude Desktop's mcpServers config:
    {
      "mcpServers": {
        "synapse": {
          "command": "python",
          "args": ["-m", "synapse.mcp.server"]
        }
      }
    }

This is part of how Synapse plugs into the broader agent ecosystem
without requiring users to instrument anything new.
"""
from .server import main

__all__ = ["main"]
