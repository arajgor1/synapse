# Synapse — VS Code extension

Catch silent collisions between AI agents (Copilot agent mode, Claude
Code, Cursor, etc.) editing the same files in your workspace.

## Install

### From source (until we publish to the VS Code Marketplace)

```bash
cd launch/ide-plugins/vscode
npm install
npm run compile
# In VS Code: F1 → "Developer: Install Extension from Location"
#   then point to this directory
```

### From the marketplace (planned)

Search "Synapse Coordination" in VS Code's Extensions panel.

## Usage

1. Install Synapse: `pip install synapse-protocol`
2. Open Settings → search "synapse" → set:
   - `synapse.agentId` (e.g., `alice-vscode`)
   - `synapse.sessionId` (shared with collaborators)
3. Run command **Synapse: Start FS watcher** (or set
   `synapse.autoStartWatcherOnLaunch`)
4. While you and your colleagues edit, Synapse logs every file write
5. Run command **Synapse: Audit current repo trace** to see conflicts

## Commands

- **Synapse: Audit current repo trace** — pick a trace JSON, see findings
- **Synapse: Start / Stop FS watcher** — capture concurrent edits
- **Synapse: Open last audit report** — re-open the most recent JSON

## Status bar

`$(eye) Synapse: watching` — click to stop
`$(circle-outline) Synapse` — click to start

## Limits

- VS Code does not expose pre-tool-call hooks for Copilot agent mode (as
  of VS Code 1.85). The FS watcher catches every write post-fact; for
  hard pre-write blocking, use the Claude Code BeforeTool hook in a
  separate Claude Code session, or wait for VS Code to ship pre-edit
  hooks.
- Multi-agent attribution is by `synapse.agentId` config; be consistent
  across collaborators.
