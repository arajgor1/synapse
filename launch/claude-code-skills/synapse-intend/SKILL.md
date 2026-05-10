---
name: synapse-intend
description: Wrap a tool call (or any side-effecting block) with synapse.intend() to claim a scope, get conflicts back if other agents are touching it, and emit a RESOLUTION when done. Use when adding Synapse coordination to user code.
---

# /synapse-intend

Wrap a tool call (or any side-effecting block) with `synapse.intend(...)`
to participate in cross-agent coordination. This is the canonical
universal API — works in any Python codebase regardless of agent
framework.

## When to invoke

Trigger when the user:

- Is writing Python that does file edits / DB writes / API calls.
- Says "add Synapse coordination", "claim this scope", "make this
  conflict-aware".
- Wants per-call control (vs the autoload pattern via
  `synapse.install(framework="...")`).

For framework-level autoload (no per-call code), use
`/synapse-install-framework` instead.

## The pattern

```python
import synapse

async with synapse.intend(
    scope=["repo.fs.app/auth.py:w"],   # what we're about to touch
    agent="me",                        # who we are
    session="my_run",                  # workflow / run id
    expected_outcome="rotate JWT secret",
    blocking=True,                     # gate window catches conflicts
    gate_ms=50,
) as i:
    if i.has_conflicts:
        # Another agent is editing this file right now
        for c in i.conflicts:
            print(f"  conflict: {c.rationale}")
        # Pivot, wait, or proceed (see /synapse-resolve-conflict)
        return  # or raise, or call a MergePolicy
    # Safe to do the work
    await write_auth_py(...)
    i.set_state_diff({"output_preview": "rotated successfully"})
# RESOLUTION emits automatically on exit
```

## Per-task agent attribution (race-free)

For multiple agents in the same process — race-safe even under
`asyncio.gather`:

```python
async def run_as(name: str):
    with synapse.with_agent(name):           # ContextVar, per-task
        async with synapse.intend(
            scope=[...], agent=name, session="run",
        ):
            ...

await asyncio.gather(run_as("alice"), run_as("bob"))
```

## Scope syntax

- `repo.fs.<path>:w` — file system write
- `repo.fs.<path>:r` — file system read
- `db.<table>:w` — database table write
- `http.<route>:w` — HTTP endpoint write
- `mcp.<tool_name>:w` — MCP tool call
- Custom: `myorg.<anything>:w`

The `:w` / `:r` suffix is the access mode. Two `:r` claims on the same
scope never conflict; any `:w` against a `:r` or `:w` does.

## Modes

- **Zero-infra** (default): in-memory bus + SQLite at `~/.synapse/state.db`.
  Single-process. `synapse.install()` with no env vars.
- **Live**: Redis (bus) + Postgres (state). Multi-process. Set
  `SYNAPSE_REDIS_URL` and `SYNAPSE_POSTGRES_DSN`.

## Common pitfalls

- **Forgot `await`.** `intend()` is an async context manager — use
  `async with`, not plain `with`.
- **Calling from sync code.** Use `asyncio.run(...)` or — better —
  the framework adapter pattern: `synapse.install(framework="langchain")`
  auto-wraps every tool call without per-call boilerplate.
- **Conflicts always empty.** If `mode=offline` (no Redis URL AND
  `SYNAPSE_OFFLINE=1`), no coordination happens. Drop the env var.

## Related

- `/synapse-install-framework` — autoload pattern, no per-call code.
- `/synapse-resolve-conflict` — what to do when `i.has_conflicts`.
- `/synapse-watch` — see your intends live in a browser.
