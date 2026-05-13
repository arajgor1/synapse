# Synapse plugin for Cline

[Cline](https://github.com/cline/cline) (formerly Claude Dev) is a
VS Code extension that runs autonomous coding agents. Synapse plugs in
via Cline's MCP support.

## Install

### Step 1 — Install Synapse
```bash
pip install synapse-protocol-py
```

### Step 2 — Add Synapse MCP server to Cline

In Cline → MCP Servers → Add server:

```json
{
  "synapse": {
    "command": "synapse-mcp",
    "disabled": false,
    "alwaysAllow": ["audit_trace_file", "list_supported_trace_formats"]
  }
}
```

### Step 3 — Set agent identity

In your shell or VS Code settings:

```bash
export SYNAPSE_AGENT_ID="alice-cline"
export SYNAPSE_SESSION_ID="team-2026-q2"
```

### Step 4 (optional) — FS watcher

```bash
SYNAPSE_AGENT_ID="alice-cline" python -m synapse.watchers.fs_watcher .
```

## What you can ask Cline

After install, Cline's agent has access to 5 Synapse tools. Try:

- *"@synapse audit_trace_file ./traces.json"*
- *"@synapse get_drift_score alice-cline bob-cursor"*

## Differences from the Continue plugin

Functionally identical — both use the same `synapse-mcp` stdio server.
Use whichever IDE / VS Code extension you prefer.
