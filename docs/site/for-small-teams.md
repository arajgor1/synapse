# Synapse for small teams (PR-based workflow)

You and 2–4 colleagues each use AI agents (Cursor / Claude Code / Copilot) on your own feature branches. Branches don't overlap textually — but PRs land in incompatible ways. **Synapse audits at PR-merge-time to catch this.**

## The pattern Synapse catches

- Alice's PR adds `users.subscription_id` (alembic migration succeeds)
- Bob's PR adds queries against `users.plan_id` (different file)
- Both PRs pass CI in isolation
- Both merge to main
- Production 500s

Git, CI, and OpenAPI codegen don't catch this because the files don't overlap. Synapse does.

## Setup (15 minutes for your team)

### 1. Each dev installs and tags their session

```bash
pip install synapse-protocol
export SYNAPSE_AGENT_ID="alice-cursor"
export SYNAPSE_SESSION_ID="our-team"
```

### 2. Each dev's CI exports their agent traces

If your agents already emit OpenInference / LangSmith traces, you're done — they go to your existing observability backend.

If not, the Synapse FS watcher works:

```bash
# .github/workflows/agent-trace-collect.yml
- name: Capture agent file writes
  run: python -m synapse.watchers.fs_watcher . &
```

### 3. Add the Synapse GitHub Action to PR review

```yaml
# .github/workflows/synapse-audit.yml
on: [pull_request]
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: arajgor1/synapse-audit-action@v1
        with:
          trace-path: 'traces/**/*.json .synapse/runs/**/*.jsonl'
          pr-comment: 'true'
```

Now every PR gets an automated comment showing cross-PR conflicts, schema drift, and the SCF resolution-tier hint (`policy` / `capability` / `temporal`).

---

## What the PR comment looks like

```markdown
## 🧠 Synapse Audit Results

| Trace file                 | Events | Writes | Conflicts |
|----------------------------|--------|--------|-----------|
| .synapse/runs/our-team.jsonl | 47     | 38     | **3**     |

**Total: 3 conflicts across 47 events.**

### Cross-agent collisions
- `app/models.py` — `alice-cursor <-> bob-claude` (kind: scope_overlap, tier: policy — billing scope)
- `app/routes/auth.py` — `alice-cursor <-> charlie-codex` (kind: stale_base_overwrite, tier: temporal)

### Belief divergences
- `subscription_table_columns`:
  - PR #142 (alice): `["id", "user_id", "plan", "seat_count"]`
  - PR #156 (bob):   `["id", "user_id", "plan_id", "seats", "status"]`
- `login_endpoint`:
  - PR #150: `/api/auth/login`
  - PR #151: `/auth/login`

_Run `synapse audit` locally to reproduce. Live coordination is available via `synapse-protocol[live]`._
```

---

## Compared to alternatives

We tested this empirically. With 2 LangGraph crews on Stripe-Lite + pytest-in-loop CI:

| Strategy | Cross-team file overlaps | Belief divergences caught |
|---|---|---|
| CI alone (`pytest tests/ -x`) | 3 (silent) | **0** |
| **CI + Synapse** | 1 (caught) | **5** |

Real schema-drift events Synapse caught in that run that CI didn't:

```
user_table_columns:
  alpha: ["id", "email", "is_admin", "created_at", "updated_at"]
  bravo: ["id", "username", "email", "password_hash", "is_admin"]

subscription_table_columns:
  alpha: ["id", "user_id", "status", "canceled_at", "cancel_reason", "grace_until"]
  bravo: ["id", "user_id", "plan_id", "status", "created_at", "canceled_at"]
```

Both branches green in their own CI. Production breaks if both merge.

---

## Limits to know

- **CI alone is not enough — but Synapse + CI is not auto-magical either.** Test 9 (Option A) showed coherence DROPPED when we added Synapse to CI under heavy CI pressure (full-file rewrites don't trigger auto_merge). Synapse adds **visibility**; whether your agents respond well to that visibility depends on your prompting.
- **Auto_merge needs incremental edits.** If your agents do full-file rewrites on every CI failure, the `auto_merge` MergePolicy can't reconcile them.

---

## Next

- [GitHub Action setup](guide/gh-action.md)
- [Live mode for stronger coordination](guide/live-mode.md)
- [Streaming dashboard](guide/streaming.md)
