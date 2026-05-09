# `synapse-mcp` CLI

```
synapse-mcp
```

Stdio Model Context Protocol server. Reads JSON-RPC requests from stdin, writes responses to stdout.

5 tools exposed:

- `audit_trace_file(path, lookback_seconds?, include_reads?)` — run audit
- `find_conflicts_in_session(path, session_id)` — filter conflicts
- `get_drift_score(path, agent_a, agent_b, session_id?)` — SAS for a pair
- `list_supported_trace_formats()` — what synapse audit can ingest
- `explain_conflict(path, conflict_index)` — plain-English explanation

Add to Claude Desktop / Cursor / Continue / Cline:

```json
{"mcpServers": {"synapse": {"command": "synapse-mcp"}}}
```
