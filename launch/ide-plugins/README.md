# Synapse IDE plugins

One Synapse install, plug it into whichever IDE / agent you use.

| IDE / agent | Plugin | Status | Install path |
|---|---|---|---|
| **Claude Code (Anthropic)** | BeforeTool/AfterTool hook | ✅ shipped | `../claude-code-hook/` |
| **Cursor** | MCP server config | ✅ shipped | `cursor/` |
| **OpenAI Codex CLI** | MCP server config | ✅ shipped | `codex-cli/` |
| **VS Code Copilot agent mode** | VS Code extension (TypeScript) | ✅ shipped | `vscode/` |
| **Aider** | git post-commit hook | ✅ shipped | `aider/` |
| **Continue** | MCP server config | ✅ shipped | `continue/` |
| **Cline** | MCP server config | ✅ shipped | `cline/` |
| **JetBrains AI / Junie** | MCP server config (planned) | 🚧 v0.2.3 | — |
| **Windsurf** | MCP server config (planned) | 🚧 v0.2.3 | — |

## How they all work

All plugins fall into one of three patterns:

### 1. Native pre-tool hook (best fidelity)
- **Claude Code** — uses Anthropic's `PreToolUse` / `PostToolUse` hooks
  to BLOCK tool calls before execution
- Highest fidelity — Synapse can route/abort/wait, not just observe

### 2. MCP server (good fidelity, model-dependent)
- **Cursor**, **Codex CLI**, **Continue**, **Cline** — Synapse exposes
  5 tools via MCP; the agent's model decides when to call them
- Good fidelity for audit; the model has to voluntarily call Synapse to
  prevent collisions before they happen

### 3. Filesystem watcher fallback (audit-only)
- **VS Code Copilot agent**, **JetBrains AI**, **Windsurf** — anywhere
  there's no pre-tool hook, the FS watcher captures every write and
  attributes it to the agent identity. Audit catches collisions
  post-hoc; no pre-write blocking.

### 4. git post-commit hook (audit on commit)
- **Aider** — runs `synapse audit` after every commit. Aider's per-edit
  commit pattern makes this granular.

## Coordinated multi-agent setup

If you have **multiple agents on the same repo** — e.g., Cursor +
Claude Code in two terminals — each agent should set its own
`SYNAPSE_AGENT_ID`:

```bash
# Terminal 1 — Cursor
export SYNAPSE_AGENT_ID="alice-cursor"
export SYNAPSE_SESSION_ID="team-2026-q2"
cursor .

# Terminal 2 — Claude Code
export SYNAPSE_AGENT_ID="alice-claude"
export SYNAPSE_SESSION_ID="team-2026-q2"
claude

# Terminal 3 (optional) — for hard collision detection across both
synapse up   # starts local Redis + Postgres
```

Now both agents emit to the same Synapse session and collisions surface
in real time (with `synapse up`) or post-hoc (without).
