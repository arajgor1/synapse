# Conflict Semantics

> How Synapse decides whether two agents' intentions overlap. This is load-bearing: without precise rules the router either over-blocks (false positives) or misses real conflicts (false negatives). Locked at v1.0.

## The Problem

Two agents emit `INTENTION` messages with `scope` arrays. When does the router fire a `CONFLICT` signal? "Just check if any string matches" is too simple — `db.users.schema` and `db.users.email` should not always conflict, but `db.users.*` should match both.

Synapse defines a small grammar over scope strings, plus rules for combining them.

## Scope Grammar

A scope is a **dotted path** with optional **read/write modifiers** and optional **glob wildcards**.

```
scope        := segment ("." segment)* [":" modifier]
segment      := name | wildcard
name         := [a-zA-Z0-9_-]+
wildcard     := "*" | "**"          // single-segment vs multi-segment
modifier     := "r" | "w" | "rw"     // read-only / write / read-write (default rw)
```

### Examples

| Scope | Meaning |
|---|---|
| `auth.middleware` | Read+write claim on `auth.middleware` |
| `auth.middleware:r` | Read-only claim |
| `auth.middleware:w` | Write-only claim |
| `auth.*` | Single-segment wildcard — matches `auth.middleware`, `auth.session`; not `auth.middleware.config` |
| `db.users.**` | Multi-segment wildcard — matches `db.users.schema`, `db.users.email.index` |
| `db.users.schema:r` | Read-only access to schema |
| `repo.file:src/auth/middleware.ts` | Filesystem-style scope; opaque to router beyond exact-match |

## Matching Rules

Two scopes **match** if their patterns intersect. Two scopes **conflict** if they match AND at least one is a write claim AND they are held by different agents.

### Step 1: Pattern intersection

| Left | Right | Intersects? |
|---|---|---|
| `auth.middleware` | `auth.middleware` | Yes (exact) |
| `auth.middleware` | `auth.*` | Yes (wildcard absorbs exact) |
| `auth.middleware` | `auth.session` | No |
| `auth.middleware.config` | `auth.*` | No (single-segment wildcard) |
| `auth.middleware.config` | `auth.**` | Yes (multi-segment wildcard) |
| `auth.*` | `auth.*` | Yes (same pattern) |
| `db.users.**` | `db.users.schema` | Yes |
| `db.**` | `db.users.**` | Yes (overlapping multi-wildcards) |

### Step 2: Read/write modifiers

Once two scopes intersect, the modifiers determine whether it's a conflict:

| Agent A | Agent B | Result |
|---|---|---|
| `:r` | `:r` | **No conflict** — concurrent reads are safe |
| `:r` | `:w` | **Conflict** — write invalidates the read |
| `:w` | `:r` | **Conflict** — same as above |
| `:w` | `:w` | **Conflict** — competing writes |
| `:rw` (default) | anything | Treated as `:w` for conflict purposes |

Read-only intentions are useful: an agent that's just *querying* a schema should not block another agent that's also just querying. Only writes serialize.

### Step 3: `blocks_others` exclusive claim

If an INTENTION sets `blocks_others: ["scope_pattern"]`, **any** other intention matching that pattern (read or write) becomes a `CONFLICT` of kind `exclusive_claim`. Use sparingly — this is the heaviest lock.

### Step 4: Same-agent self-overlap

An agent's own intentions never conflict with each other. This lets one agent hold multiple active intentions simultaneously (e.g., a long-running write plus a quick read).

## Dependency vs Conflict

Two related but distinct relationships:

- **Conflict**: scopes intersect, at least one writes → `CONFLICT` message, downstream agent should pivot or wait
- **Dependency**: agent B's INTENTION declares it depends on agent A's pending RESOLUTION → no `CONFLICT`, but B is informed and can wait if it chooses

v1.0 implements conflict only. Dependency declarations land in v1.1 via an optional `depends_on` field on INTENTION.

## Examples Walk-Through

**Case 1 — clean parallel work**
```
Agent A: scope=["auth.middleware:w"]
Agent B: scope=["auth.session:w"]
```
No intersection (`middleware` ≠ `session`). No conflict.

**Case 2 — concurrent reads**
```
Agent A: scope=["db.users.schema:r"]
Agent B: scope=["db.users.schema:r"]
```
Intersect. Both read-only. **No conflict.**

**Case 3 — read vs write**
```
Agent A: scope=["db.users.schema:r"]
Agent B: scope=["db.users.schema:w"]
```
Intersect. One write. **Conflict** (B receives `CONFLICT` of kind `scope_overlap`).

**Case 4 — wildcard catches narrow scope**
```
Agent A: scope=["db.users.**:w"]
Agent B: scope=["db.users.email:w"]
```
Intersect (multi-segment wildcard). Both write. **Conflict.**

**Case 5 — exclusive claim**
```
Agent A: scope=["auth.middleware:w"], blocks_others=["auth.**"]
Agent B: scope=["auth.session:r"]
```
Intersect via `blocks_others` pattern. **Conflict** of kind `exclusive_claim`.

## Implementation Notes

The router implements this in two stages:

1. **Postgres GIN index over `scope::text[]`** — initial coarse intersection check via `&&` (array overlap operator). This is the fast path — sub-millisecond at thousands of active intentions.
2. **Pattern resolver in router code** — refines the GIN match with wildcard expansion and modifier checks. Implemented as pure Python; no LLM in the conflict path.

Edge case: multi-segment wildcards (`**`) cannot be expressed as plain array overlap. The router stores expanded forms (`auth.middleware`, `auth.session`, ...) when known, and falls back to a regex match for the unexpanded case. The regex match is bounded by total active intentions per session (typically < 100), so it's still sub-millisecond.

## Future Extensions (v1.1+)

- **Path-based scopes** for filesystem coordination (`repo.path:src/auth/middleware.ts`) with structural understanding (line ranges, AST nodes)
- **Time-bounded claims** (`scope:w@5m` — claim expires in 5 minutes)
- **Probabilistic dependencies** (`depends_on` with confidence)
- **Structural diff awareness** — two agents touching the same file in non-overlapping byte ranges should not conflict
