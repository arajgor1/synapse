---
name: synapse-explain
description: Explain WHY Synapse flagged a particular scope or conflict — walk through the inference (which scope-inference rule matched, which lookback window, which conflict-detection layer fired). Use when the user asks "why is this a conflict?" or "what does this scope string mean?"
---

# /synapse-explain

Walk the user through why Synapse made a particular call —
which scope-inference rule fired, which conflict-detection layer
flagged it, what tier the resolution-hint suggests.

## When to invoke

Trigger when the user:

- Asks "why did Synapse flag this?"
- Asks "what does the scope `repo.fs.app/auth.py:w` mean?"
- Asks "why is `kind=stale_base_overwrite` and not `scope_overlap`?"
- Asks "what does `resolution_tier_hint=capability` mean?"
- Wants to understand why a particular tool call was classified as a
  write vs a read.

## Scope inference

Synapse infers a scope from each tool call's name + args. Run
`synapse explain-tool <tool_name>` (or the MCP `explain_conflict` tool)
to see which rule matched. Common patterns:

| Tool name shape | Inferred scope | Notes |
|---|---|---|
| `edit_file`, `write_file`, `str_replace_editor` | `repo.fs.<path>:w` | `path` arg required |
| `read_file`, `cat`, `head` | `repo.fs.<path>:r` | Read-class, never conflicts unless `--include-reads` |
| `schema_migration`, `add_column`, `alter_table` | `db.<table>:w` | `table` or `table_name` arg |
| `cancel_subscription`, `process_refund` | `http.<route>:w` | HTTP-shaped route |
| Anything without a recognized pattern | None (skipped) | Free-form tools don't conflict |

## Conflict kinds

`scope_overlap` (the canonical one):
- Two agents have **active** intentions whose scopes overlap.
- One started before the other resolved.
- Always a real concurrent-write hazard.

`stale_base_overwrite`:
- Agent A wrote and resolved.
- Agent B starts writing the same scope within `resolved_lookback_ms`
  (default 60s).
- B likely hasn't seen A's change yet — B's write would clobber A's
  unless B pulls first.

`causal_violation` (audit-side only):
- Detected via SAS (semantic alignment score) drift on shared scopes.
- Two agents disagree about what they wrote.

## Resolution tier hints

Synapse suggests a tier based on the conflict's shape:

- **policy** — A merge policy can resolve automatically (text composes;
  use auto_merge).
- **capability** — One agent has the role to write this scope, the
  other doesn't. Route to the right agent.
- **temporal** — A simple time-based queue (queue_behind) suffices.
- **escalation** — Needs human review (sensitive scope, semantic
  conflict).

## Walking through a real example

```
Conflict
  scope          : repo.fs.app/auth.py:w
  agent          : bob (intent)
  conflicting    : alice (active intention)
  kind           : scope_overlap
  rationale      : "Your intention's scope ['repo.fs.app/auth.py:w']
                    overlaps with 1 active intention(s) by other
                    agent(s) (immediate self-check)."
  tier hint      : temporal
```

What this tells the user:

- alice claimed `app/auth.py` for write, hasn't released yet
- bob arrived second on the same file
- This is a CONCURRENT write, not a stale-base-overwrite
- A time-based wait would resolve it (alice will release eventually)
- bob's options: queue_behind, retry_with_backoff, or work_on_different_scope

## Common pitfalls

- **"My tool is `awesome_tool` — Synapse doesn't infer a scope."** Add
  a custom rule via `synapse.audit.scope_inference.register_rule(...)`
  or pass an explicit scope to `synapse.intend(scope=[...])`.
- **"My tool returns CONFLICT but I don't see why."** Check
  `i.conflicts[0].rationale` — it's always a structured English string.
- **"`--include-reads` flagged a bunch of false positives."** Read-class
  tools (catalogued in `synapse.audit.events.is_write`) shouldn't
  conflict by default. Only enable `--include-reads` when investigating
  read-after-write inconsistency, not for normal audits.

## Related

- `/synapse-audit` — run a fresh audit on the user's trace.
- `/synapse-resolve-conflict` — pick a policy.
- Full taxonomy: `docs/site/reference/taxonomy.md`.
