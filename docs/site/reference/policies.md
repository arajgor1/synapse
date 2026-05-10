# MergePolicy reference

When ``synapse.intend()`` detects a CONFLICT, the configured **MergePolicy** decides what to do. v0.2.2 ships ten built-in policies — five low-level primitives and five higher-level templates that cover the patterns real users actually need.

Pass a policy via ``synapse.install(merge_policy=...)`` (process default) or per-call via ``synapse.intend(merge_policy=...)``. Strings, attribute references, and direct instances all work:

```python
import synapse

# String
synapse.install(merge_policy="queue_behind")

# Attribute (recommended — IDE autocomplete)
synapse.install(merge_policy=synapse.MergePolicy.queue_behind)

# Direct instance with custom params
from synapse.policies import RetryWithBackoffPolicy
synapse.install(merge_policy=RetryWithBackoffPolicy(max_attempts=8, initial_backoff_ms=100))
```

## At-a-glance

| Name | Decision on conflict | Use when |
|---|---|---|
| ``no_op`` | PROCEED (silent) | dev/debug only — defeats coordination |
| ``redirect`` *(default)* | PROCEED + structured rationale | safest default; surface to your agent's LLM |
| ``wait`` | sleep then retry once | quick-and-dirty backoff |
| ``abort`` | raise ``SynapseConflict`` | hard fail, let the framework escalate |
| ``auto_merge`` | LLM merges the writes | text/code where two writers' edits compose |
| ``queue_behind`` | poll until others resolve, then PROCEED | serialise on a hot scope |
| ``wait_for_other`` | alias for ``queue_behind`` | friendlier name |
| ``work_on_different_scope`` | pivot to per-agent variant of the path | parallel drafts (Researcher/Writer/Editor) |
| ``escalate_to_human`` | emit BLOCK envelope + ABORT | high-stakes scope (billing, deploys) |
| ``retry_with_backoff`` | exponential backoff retry | transient contention; abort on exhaustion |

## The five templates (v0.2.2a4)

### ``QueueBehindPolicy`` / ``WaitForOtherPolicy``

Polls the state graph at ``poll_interval_ms`` (default 50ms) until **every** conflicting intention's status flips to ``resolved``. On timeout, fires ``on_timeout`` (default ``MergeDecision.ABORT``).

```python
from synapse.policies import QueueBehindPolicy

async with synapse.intend(
    scope=["repo.fs.shared/db.py:w"],
    agent="me",
    merge_policy=QueueBehindPolicy(timeout_ms=10_000, poll_interval_ms=100),
) as i:
    # We get here only after every other claimant resolves, OR
    # SynapseConflict raises if we time out.
    ...
```

Use when: hot shared resource that's never touched for long but is touched often (a config file, a feature-flag store).

### ``WorkOnDifferentScopePolicy``

Auto-pivots a path-shaped argument so the conflict goes away. Looks at ``proposed_action`` for keys ``path``, ``file_path``, ``filename``, ``target``, ``out_path`` and rewrites the **first match** to ``foo.<agent>.<ext>``.

```python
from synapse.policies import WorkOnDifferentScopePolicy

async with synapse.intend(
    scope=["repo.fs.drafts/post.md:w"],
    agent="alice",
    merge_policy=WorkOnDifferentScopePolicy(),
    proposed_action={"path": "drafts/post.md", "content": "..."},
) as i:
    if i.merged_action:  # filled when policy pivoted
        await write(**i.merged_action)  # path is now drafts/post.alice.md
```

Use when: parallel drafts (Researcher/Writer/Editor) where the *value* of writing in parallel is preserving each agent's contribution. The CrewAI marketing demo (``examples/crewai-marketing/``) shows this.

### ``EscalateToHumanPolicy``

Emits a high-urgency BLOCK envelope on the bus describing the conflict, then aborts the intention with ``SynapseConflict``. Downstream notification integrations (Slack/PagerDuty, the Synapse hosted dashboard) can fire alerts on the BLOCK.

```python
from synapse.policies import EscalateToHumanPolicy

synapse.install(
    merge_policy="redirect",
    critical_scopes=["billing.*", "prod.deploy.*"],
)
async with synapse.intend(
    scope=["billing.user_subscription:w"],
    agent="refund_bot",
    merge_policy=EscalateToHumanPolicy(urgency="critical"),
):
    ...
```

Use when: scope is sensitive enough that "the wrong write" must never silently happen. Pair with ``critical_scopes`` for belt-and-suspenders.

### ``RetryWithBackoffPolicy``

Re-checks the state graph for the conflicting intentions to flip to ``resolved`` after each backoff. Default ``max_attempts=5`` with ``initial_backoff_ms=50`` doubling up to ``max_backoff_ms=2000``.

```python
from synapse.policies import RetryWithBackoffPolicy

async with synapse.intend(
    scope=["repo.fs.cache.json:w"],
    agent="cache_warmer",
    merge_policy=RetryWithBackoffPolicy(
        max_attempts=8, initial_backoff_ms=20, max_backoff_ms=500,
        on_exhausted=synapse.MergeDecision.ABORT,
    ),
):
    ...
```

Use when: transient contention you expect to clear quickly (cache invalidation, rate-limited APIs). Cheaper than ``queue_behind`` for very-short conflict windows.

## How the policy chain runs in ``intend()``

1. ``synapse.intend()`` emits the INTENTION + does the active-scope fast path check (v0.2.2a4 — see [latency](../../../bench/LATENCY.md)).
2. If conflicts surface, ``critical_scopes`` is checked first — ANY match → forced ABORT regardless of policy.
3. The configured ``merge_policy.resolve(handle, conflicts, proposed_action)`` runs.
4. Policy returns a ``MergeAction(decision=...)`` :
   * ``PROCEED`` — body of the ``async with`` block runs as normal.
   * ``ABORT`` — ``SynapseConflict`` raises before the body.
   * ``MERGED`` — ``handle.merged_action`` is filled; body should use it.
   * ``WAIT`` — runtime sleeps the timeout, then proceeds.

## Custom policies

Subclass ``MergePolicy`` and implement ``resolve``:

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

## Performance

Policy ``resolve`` runs only when a conflict is detected. The active-scope fast path means **no policy code runs on the hot no-conflict path** — see [bench/LATENCY.md](../../../bench/LATENCY.md). Median overhead with no conflict: 1.59ms.
