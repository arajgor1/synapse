# Synapse hook for Claude Code

Coordinate multiple concurrent Claude Code sessions on the same repo.

## When you'd want this

Two Claude Code sessions on the same codebase will silently overwrite each other and disagree on schemas. This hook makes them visible to Synapse.

Common scenarios:
- You're running Cursor in the IDE + Claude Code in a terminal — two agents, same files
- Multiple Claude Code sessions in tmux panes, each focused on a different feature
- A team where each dev runs Claude Code locally on the same repo

## Install

1. Copy `synapse-pretooluse.py` somewhere stable (e.g., `~/.synapse/hooks/`).

2. Add to your Claude Code `settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python ~/.synapse/hooks/synapse-pretooluse.py"
          }
        ]
      }
    ]
  }
}
```

3. Set environment variables before launching each Claude Code session:

```bash
export SYNAPSE_AGENT_ID=alice
export SYNAPSE_SESSION_ID=team-multidev
claude
```

In a different terminal:

```bash
export SYNAPSE_AGENT_ID=bob
export SYNAPSE_SESSION_ID=team-multidev
claude
```

## What it does

- **Live mode** (Synapse runtime running): emits a Synapse INTENTION envelope before each Edit/Write/MultiEdit. If another session is currently writing the same file or just did, the hook blocks/routes the call.
- **Audit-only mode** (no Synapse runtime): writes a JSONL event to `.synapse/runs/<session>.jsonl`. Run `synapse audit .synapse/runs/<session>.jsonl` post-hoc to see what collided.

## Limits (honest)

- This is a **wrapper** path — the hook fires on Claude Code's tool dispatch, but reduced fidelity vs SDK-native integration:
  - Cannot extract beliefs from tool *output* (no LLM-call-result access).
  - Only file-path-level scope, not deeper semantic.
- For full live semantic detection, use `pip install synapse-protocol[live]` with one of the 12 SDK adapters.

## Same hook for Codex CLI / Aider

The hook is generic — Codex CLI, Aider, and any other tool with pre-tool-use hooks can call this script. Set the `tool_name` and `tool_input` JSON shape Claude Code sends; we read just `file_path` and the rest is generic.
