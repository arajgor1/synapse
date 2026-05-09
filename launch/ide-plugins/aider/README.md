# Synapse plugin for Aider

Aider has a unique advantage: it commits per-edit. That makes Synapse
integration cleaner than for any other agent — every Aider commit IS
a checkpoint we can audit against.

## What it does

- **Git post-commit hook**: after every Aider commit, runs `synapse
  audit` against the trace data and surfaces any cross-agent conflicts
  with concurrent agents (Cursor, Claude Code, Codex, etc.) on the
  same repo.
- **MCP integration**: Aider can call Synapse tools to check before
  starting work on a file, via MCP-aware routing in your `.aider.conf.yml`.

## Install (2 minutes — Aider's the easiest)

### Step 1 — Install Synapse
```bash
pip install synapse-protocol
```

### Step 2 — Install the git post-commit hook

Run this from your repo root:

```bash
python -m synapse.integrations.aider_hook install
```

(Adds 6 lines to `.git/hooks/post-commit`.)

### Step 3 — Tag your Aider session

```bash
export SYNAPSE_AGENT_ID="alice-aider"
export SYNAPSE_SESSION_ID="team-2026-q2"
aider
```

After every commit, the hook runs:

```bash
synapse audit .synapse/runs/${SYNAPSE_SESSION_ID}.jsonl --no-html
```

If conflicts exist, you'll see a colored summary in the terminal and
the JSONL report at `.synapse/runs/<session>.jsonl`.

### Step 4 (optional) — Run watchers for the OTHER agents

If colleagues are using Cursor / Claude Code / Codex on the same repo
without their own Synapse hooks, run an FS watcher in a sidecar to
attribute their writes:

```bash
SYNAPSE_AGENT_ID="bob-cursor" python -m synapse.watchers.fs_watcher .
```

Now Aider's post-commit audit will see both crews.

## Why Aider integrates better than the others

Aider's per-edit commit pattern means there's a natural attribution
boundary on every action. Most agents (Cursor, Claude Code) batch
many edits into one apparent "session" without commits in between.
Aider gives Synapse explicit, granular ground truth.

## Limits

- The post-commit hook runs after the commit lands — it's audit-mode,
  not blocking. To block pre-commit on conflicts, install a
  `pre-commit` git hook that checks `.synapse/runs/*.jsonl` for active
  CONFLICT envelopes.
