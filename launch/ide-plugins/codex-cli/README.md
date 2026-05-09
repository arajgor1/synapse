# Synapse plugin for OpenAI Codex CLI

Coordinate Codex CLI sessions running on the same repo as your other
agents (Cursor, Claude Code, Aider, etc.).

## What it does

- **MCP server**: gives Codex CLI's agent direct access to Synapse's
  audit + coordination tools.
- **FS watcher sidecar**: captures every file write Codex makes and
  attributes them to the right agent identity, so audit can detect
  collisions with other concurrent sessions.

## Install (3 minutes)

### Step 1 — Install Synapse
```bash
pip install synapse-protocol
```

### Step 2 — Add MCP to Codex CLI

Codex CLI reads MCP config from `~/.codex/config.json`. Add:

```json
{
  "mcpServers": {
    "synapse": {
      "command": "synapse-mcp"
    }
  }
}
```

### Step 3 — Tag your session

Before launching `codex`:

```bash
export SYNAPSE_AGENT_ID="alice-codex-cli"
export SYNAPSE_SESSION_ID="team-2026-q2"
```

### Step 4 (optional) — FS watcher sidecar

Codex CLI doesn't expose pre-tool hooks today. To capture collisions
with other agents that also lack hooks (Aider, Cursor agent), run the
FS watcher in a sidecar terminal:

```bash
cd /path/to/your/repo
SYNAPSE_AGENT_ID="alice-codex-cli" python -m synapse.watchers.fs_watcher .
```

Now every file write Codex makes is logged. Run `synapse audit
.synapse/runs/team-2026-q2.jsonl` periodically to see what collided.

## What you can ask Codex to do

- *"Synapse, audit the langsmith export at ./traces.json"*
- *"Synapse, what's drifting between codex-cli and claude-code in this run?"*

## Limits

- Codex CLI's MCP tool-call discipline depends on the model. If the model
  doesn't call the Synapse MCP tools voluntarily, only the FS watcher
  sidecar catches collisions.
- Same `SYNAPSE_AGENT_ID` discipline as the Cursor plugin.

## See also

- Cursor plugin: `../cursor/`
- Claude Code plugin: `../../claude-code-hook/`
- VS Code Copilot plugin: `../vscode/`
