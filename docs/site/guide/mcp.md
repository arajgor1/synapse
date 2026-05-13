# MCP server (`synapse-mcp`)

```bash
pip install synapse-protocol-py
synapse-mcp
```

Stdio Model Context Protocol server. Add to Claude Desktop / Cursor / Continue / Cline:

```json
{"mcpServers": {"synapse": {"command": "synapse-mcp"}}}
```

5 tools exposed:
- `audit_trace_file(path)` — run audit on a trace JSON
- `find_conflicts_in_session(path, session_id)` — filter conflicts to one session
- `get_drift_score(path, agent_a, agent_b)` — SAS for an agent pair
- `list_supported_trace_formats()` — formats supported by audit
- `explain_conflict(path, conflict_index)` — plain-English explanation
