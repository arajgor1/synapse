---
name: synapse-resolve-conflict
description: Pick the right MergePolicy when synapse.intend() detects a conflict. Use when the user's IntentionHandle.has_conflicts == True and they need to decide what to do (pivot, wait, abort, escalate, retry, auto-merge).
---

# /synapse-resolve-conflict

When `synapse.intend(...)` returns a handle with `has_conflicts == True`,
the user has 10 built-in resolution strategies (and can write custom
ones). This skill picks the right one.

## When to invoke

Trigger when the user:

- Sees `IntentionHandle.has_conflicts == True` and asks "what should I do?"
- Wants to set a default policy at install time.
- Is designing a multi-agent system and asks about coordination policies.

## The 10 built-in policies

| Name | Decision | Use when |
|---|---|---|
| `redirect` *(default)* | PROCEED + structured rationale | Safest default; surface the conflict to your agent's LLM and let IT decide |
| `wait` | sleep then retry once | Quick-and-dirty backoff |
| `abort` | raise `SynapseConflict` | Hard fail; framework handles retry/escalate |
| `auto_merge` | LLM merges the writes | Text/code where two writers' edits compose |
| `no_op` | PROCEED silently | Dev/debug only — defeats coordination |
| `queue_behind` | poll until others resolve, then PROCEED | Hot shared resource that's never held long but is hit often |
| `wait_for_other` | alias for queue_behind | Friendlier name in code |
| `work_on_different_scope` | pivot path arg to per-agent variant | Parallel drafts (Researcher/Writer/Editor) |
| `escalate_to_human` | emit BLOCK envelope + ABORT | High-stakes scope (billing, deploys); pair with critical_scopes |
| `retry_with_backoff` | exponential backoff retry | Transient contention; abort on exhaustion |

## Decision tree

```
Is the scope production-sensitive (billing, deploy, schema)?
  YES -> escalate_to_human + critical_scopes=["billing.*", ...]
  NO  -> continue

Are the two writes semantically composable (text, JSON config, etc)?
  YES -> auto_merge (requires synapse.set_llm())
  NO  -> continue

Will the conflict clear quickly (<5 sec)?
  YES -> retry_with_backoff or queue_behind
  NO  -> continue

Can each agent work on a sibling scope (drafts/post.alice.md vs .bob.md)?
  YES -> work_on_different_scope
  NO  -> redirect (let the agent's LLM pivot in its own way)
```

## Setting a default at install time

```python
synapse.install(
    framework="langgraph",
    merge_policy=synapse.MergePolicy.queue_behind,
    critical_scopes=["billing.*", "prod.deploy.*"],
)
```

`critical_scopes` short-circuits to ABORT regardless of the policy
when any matched scope is hit — belt-and-suspenders for sensitive
operations.

## Per-call override

```python
async with synapse.intend(
    scope=["repo.fs.shared/db.py:w"],
    agent="me",
    merge_policy=synapse.MergePolicy.queue_behind,
    # OR a custom-tuned instance:
    # merge_policy=QueueBehindPolicy(timeout_ms=10_000, poll_interval_ms=100),
) as i:
    ...
```

## Custom policy

```python
from synapse.policies import MergePolicy, MergeAction, MergeDecision

class MyPolicy(MergePolicy):
    name = "my_policy"
    async def resolve(self, handle, conflicts, proposed_action=None):
        if any("auth" in s for s in handle.scope):
            return MergeAction(
                decision=MergeDecision.ABORT,
                rationale="auth scope policy: never auto-merge",
            )
        return MergeAction(decision=MergeDecision.PROCEED, rationale="ok")

synapse.install(merge_policy=MyPolicy())
```

## Common pitfalls

- **Default `redirect` does nothing scary.** It just adds rationale and
  proceeds. If the user wants real blocking, pick `abort` or
  `escalate_to_human`.
- **`auto_merge` requires `synapse.set_llm()`**. Without an LLM
  configured, it falls back to `redirect` semantics.
- **`queue_behind` polls** — set sensible `timeout_ms` (default 30s).
  Times out → ABORT (or whatever `on_timeout` is set to).

## Related

- `/synapse-intend` — the basic claim-and-act pattern.
- `/synapse-explain` — why did Synapse flag this scope?
- Full reference: `docs/site/reference/policies.md`.
