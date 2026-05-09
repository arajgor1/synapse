# Synapse plugin for Cursor

Coordinate multiple Cursor sessions on the same repo, or one Cursor session
running alongside Claude Code / Codex CLI / Aider on the same files.

## What it does

- **Pre-edit gate**: before Cursor's agent makes a `Edit`, `MultiEdit`, or
  `Write` tool call, Synapse checks whether another agent (Cursor session,
  Claude Code session, etc.) is currently writing or just wrote that file.
- **If conflict detected**: Cursor sees a denial and gets fed back a
  rationale string explaining which other agent owns the file. Cursor's
  next plan can either retry, pivot, or escalate.
- **Audit-only fallback**: if the live Synapse runtime isn't running, the
  hook writes an MCP-compatible JSONL event log to `.synapse/runs/` so
  you can run `synapse audit` post-hoc.

## Install (3 minutes)

### Step 1 — Install Synapse
```bash
pip install synapse-protocol
```

### Step 2 — Add the MCP server to Cursor

In Cursor → Settings → MCP → Add new MCP server:

```json
{
  "synapse": {
    "command": "synapse-mcp"
  }
}
```

Cursor's agent will now have access to 5 Synapse tools:
- `audit_trace_file(path)`
- `find_conflicts_in_session(session_id)`
- `get_drift_score(agent_a, agent_b)`
- `list_supported_trace_formats()`
- `explain_conflict(conflict_index)`

### Step 3 — Set per-session agent identity

In your shell before launching Cursor:

```bash
export SYNAPSE_AGENT_ID="alice-cursor"     # name this Cursor instance
export SYNAPSE_SESSION_ID="team-2026-q2"   # share with other devs/agents
```

Then your colleague (or your other Cursor window) does:

```bash
export SYNAPSE_AGENT_ID="bob-cursor"
export SYNAPSE_SESSION_ID="team-2026-q2"
```

When both touch the same file, Synapse audit will surface the collision.

### Step 4 (optional, live coordination)

For real-time blocking instead of post-hoc audit, also start the Synapse
runtime:

```bash
synapse up   # starts Redis + Postgres via docker-compose
```

Now Synapse will block conflicting writes mid-flight, not just log them.

## What you can ask Cursor's agent to do

After install, you can ask Cursor things like:

- *"Use synapse to check if anyone else has touched models.py recently."*
- *"Audit my last LangGraph trace at ./traces.json for conflicts."*
- *"What's the SAS drift score between alice-cursor and bob-cursor?"*

Cursor's agent will call the Synapse MCP tools and surface the results.

## How this differs from Cursor's built-in collaboration

Cursor's built-in collaboration is great for human-edits in a shared
session. Synapse is for the case where **AI agents** (Cursor's agent +
your other agents) are simultaneously writing to the same files — a
problem that pre-dates and is orthogonal to human-collaborative editing.

## Limits

- Cursor doesn't (yet) expose pre-tool hooks like Claude Code does, so
  Synapse can only block via the MCP tools the agent voluntarily calls,
  not via hard interception. For hard interception, use the FS watcher
  fallback (`python -m synapse.watchers.fs_watcher .`) in a sidecar
  terminal.
- Multi-agent attribution is by env var (`SYNAPSE_AGENT_ID`); be
  consistent across sessions.

## See also

- Claude Code plugin: `../../claude-code-hook/`
- VS Code Copilot plugin: `../vscode/`
- Codex CLI plugin: `../codex-cli/`
