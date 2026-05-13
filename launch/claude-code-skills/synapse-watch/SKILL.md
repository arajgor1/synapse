---
name: synapse-watch
description: Start the Synapse live coordination dashboard. Opens a browser tab showing every tool call + cross-agent conflict in real time. Zero infrastructure — works without Redis/Postgres.
---

# /synapse-watch

Start the live coordination dashboard. Use when the user wants to SEE
their agents' activity (and any silent collisions) in real time, before
running their agent code.

## When to invoke

Trigger when the user:

- Says "watch my agents", "see live coordination", "start the dashboard".
- Wants to demo Synapse to someone else.
- Is about to run a multi-agent script and wants to monitor it.
- Asks "is Synapse actually catching anything?"

Do NOT invoke for post-hoc analysis of an existing trace file — use
`/synapse-audit` for that.

## How to run

```bash
pip install synapse-protocol-py
synapse watch --session demo
```

The CLI:

1. Auto-engages zero-infra mode (in-memory bus + SQLite at
   `~/.synapse/state.db`) — no Redis or Postgres needed.
2. Starts a WebSocket streaming server on a free port.
3. Starts a static HTML dashboard server on a free port.
4. Auto-opens the dashboard URL in the user's default browser.
5. Tails `.synapse/runs/<session>.jsonl` for live events.

## What the user does next

In a SECOND terminal in the same project tree:

```bash
SYNAPSE_SESSION_ID=demo python their_agent_script.py
```

Every `synapse.intend(...)` call in their code shows up live in the
dashboard. Conflicts highlight in red.

## Useful flags

- `--port 8765` — WebSocket port (auto-bumps if in use)
- `--http-port 8766` — Dashboard HTTP port (auto-bumps if in use)
- `--bind 127.0.0.1` (default) — localhost only. **Do not set 0.0.0.0
  on a shared network — agent activity becomes LAN-readable.**
- `--no-browser` — skip auto-opening the browser (useful for headless / CI).
- `--once 60` — exit after N seconds (smoke-testing).

## Verifying it works

After step 4, the dashboard at `http://localhost:8766/` should show
"live" connection state. If it shows "disconnected", the WebSocket
server didn't bind correctly — check for port conflicts via
`netstat -ano | findstr 8765` (Windows) or `lsof -i :8765` (mac/linux).

## Common pitfalls

- **Dashboard shows 0 events.** The user's agent code isn't reaching
  the JSONL audit log. Either set `SYNAPSE_AUDIT_LOG=$(pwd)/.synapse/runs/<session>.jsonl`
  in their script's terminal, OR run their script from inside the project
  root (auto-discovery walks up to find `.synapse/runs/`).
- **Browser doesn't open.** Use `--no-browser` and copy the URL printed
  in the CLI banner.
- **"Address in use".** The CLI auto-bumps ports; re-read the printed
  banner for the actual port chosen.

## Related

- `/synapse-intend` — programmatic claim from a Python script.
- `/synapse-resolve-conflict` — what to do when the dashboard shows red.
