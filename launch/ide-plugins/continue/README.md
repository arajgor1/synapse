# Synapse plugin for Continue

[Continue](https://continue.dev) is the open-source AI coding assistant
for VS Code and JetBrains. Synapse plugs in via Continue's MCP support.

## Install

### Step 1 — Install Synapse
```bash
pip install synapse-protocol-py
```

### Step 2 — Add Synapse to Continue's config

Edit `~/.continue/config.json` (Continue → Settings → Open config) and add:

```json
{
  "experimental": {
    "modelContextProtocolServers": [
      {
        "transport": {
          "type": "stdio",
          "command": "synapse-mcp"
        }
      }
    ]
  }
}
```

### Step 3 — Set per-session agent identity

```bash
export SYNAPSE_AGENT_ID="alice-continue"
export SYNAPSE_SESSION_ID="team-2026-q2"
```

Then launch your IDE.

### Step 4 (optional) — FS watcher sidecar

If your team is using multiple agents on the repo, run the watcher to
attribute writes:

```bash
SYNAPSE_AGENT_ID="alice-continue" python -m synapse.watchers.fs_watcher .
```

## What you can ask Continue

- *"Use Synapse to audit our last LangGraph trace"*
- *"What's drifting between alice-continue and bob-cursor?"*
- *"Show me the conflict explanation for #2 in the last audit"*

## See also

- VS Code Copilot: `../vscode/`
- Cursor: `../cursor/`
