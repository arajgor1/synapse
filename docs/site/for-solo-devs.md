# Synapse for solo devs

You run Cursor in your IDE and Claude Code in a terminal, simultaneously, on the same repo. Sometimes you forget which one was last on `models.py` and overwrite your own work. **Synapse catches this.**

## The 90-second setup

### 1. Install
```bash
pip install synapse-protocol
```

### 2. Tag each agent session

Different terminal per agent, different `SYNAPSE_AGENT_ID`:

```bash
# Terminal 1 — Cursor
export SYNAPSE_AGENT_ID="me-cursor"
export SYNAPSE_SESSION_ID="solo-2026"
cursor .

# Terminal 2 — Claude Code
export SYNAPSE_AGENT_ID="me-claude"
export SYNAPSE_SESSION_ID="solo-2026"
claude
```

### 3. Run the FS watcher in any terminal

```bash
python -m synapse.watchers.fs_watcher .
```

It logs every file write to `.synapse/runs/solo-2026.jsonl` with the agent ID.

### 4. Audit anytime
```bash
synapse audit .synapse/runs/solo-2026.jsonl
```

Output: a list of files where both agents touched the same path, plus the SAS drift score showing how aligned (or not) your two agents are.

---

## Real example

Here's an actual run from our test suite — two real `claude -p` sessions on a shared Stripe-Lite repo:

```
Loaded 28 events from 1 session(s).
  write events:   28
  conflicts:      21 (15 scope_overlap, 6 stale_base_overwrite)
  by tier:        21 temporal
  ── unique cross-agent collisions on shared paths:
    app/models.py          : me-cursor <-> me-claude
    app/main.py            : me-cursor <-> me-claude
    app/routes/admin.py    : me-cursor <-> me-claude
    app/routes/invoices.py : me-cursor <-> me-claude
    app/routes/subscriptions.py : me-cursor <-> me-claude
    tests/test_cancel.py   : me-cursor <-> me-claude
    app/auth.py            : me-cursor <-> me-claude
```

7 files where I would have silently overwritten my own work.

---

## What you can ask Cursor / Claude Code via MCP

If you set up the [MCP server](guide/mcp.md), each agent has 5 Synapse tools available:

- *"Synapse, audit my last LangGraph trace at ./traces.json"*
- *"Synapse, what's drifting between me-cursor and me-claude?"*
- *"Synapse, explain conflict #2 from the last audit"*

---

## Limits to know

- **Cursor doesn't expose pre-tool-call hooks** (as of 2026). Synapse can audit what already happened, not block in flight. For pre-write blocking on Claude Code, install the [BeforeTool hook](https://github.com/arajgor1/synapse/tree/main/launch/claude-code-hook).
- **FS-watcher attribution is by `SYNAPSE_AGENT_ID` env var.** If you forget to set it differently per terminal, both watchers see "default" and the audit can't distinguish them.

---

## Next

- [Live mode](guide/live-mode.md) — block conflicts in flight (requires `synapse up`)
- [Real-time dashboard](guide/streaming.md) — see conflicts in your browser as they happen
