# Synapse Examples

## Running the conflict demo

The Phase 1 deliverable. Two agents, same scope, conflict detected and routed in real-time.

### Prerequisites

1. **Docker Desktop** (or any Docker Engine) — for Redis + Postgres
2. **Python 3.11+**

### One-time setup

From the repo root:

```bash
# Bring up Redis + Postgres with the initial schema applied
docker compose up -d

# Install the SDK in editable mode
pip install -e sdk-python
```

Verify infra is healthy:

```bash
docker compose ps
# Both synapse-redis and synapse-postgres should be (healthy)
```

### Run

```bash
python examples/two_agents_conflict_demo.py
```

### Expected output

```
======================================================================
  Synapse two-agent conflict demo  [session=demo_xxxxxxxx]
======================================================================

  Step 1: Agent A claims auth.middleware (write)
  Agent A intention emitted: 01HQ...
  Agent A conflicts at gate: []

  Step 2: Agent B tries to claim the same scope (with gate)
  Agent B intention emitted: 01HQ...

  Step 3: CONFLICT detected — Agent B pivots
  Kind:               scope_overlap
  Overlapping scopes: ['auth.middleware:w']
  Suggested:          pivot
  Rationale:          Your intention's scope ['auth.middleware:w'] overlaps with 1 active intention(s) by other agent(s).
  Conflicts with:     agent_a (intention=01HQ...) on scope ['auth.middleware:w']

  Step 4: Agent B narrows scope and retries
  Agent B retry intention: 01HQ...
  Agent B conflicts on retry: []

  Step 5: Agent A resolves; both finish cleanly
  Both intentions resolved.

[demo] Coordination protocol verified end-to-end.
```

### What you just verified

- Agent registration in Postgres
- Envelope construction with ULIDs
- INTENTION published to the session stream
- Router consumes from the session stream via consumer group
- L2 conflict detection via SQL + Python scope matcher
- CONFLICT routed to the offending agent's inbox
- Pre-execution gate (`blocking=True`) drains inbox during the gate window
- Agent receives the structured CONFLICT and acts on it
- Pivot to non-overlapping scope succeeds without conflict

### Reset between runs

The demo uses a fresh random session ID each time, so re-running is safe. To wipe everything:

```bash
docker compose down -v   # removes volumes (Postgres + Redis state)
docker compose up -d     # fresh start, migrations re-applied
```

## Running the unit tests (no Docker needed)

```bash
pip install pytest pytest-asyncio
pytest sdk-python/tests/
```

39 tests covering:
- Scope matcher (exact, wildcards, modifiers, walk-through examples from `spec/conflict-semantics.md`)
- Envelope construction and ULID validation
- Pydantic message models for all 8 message types
- Mock adapter streaming, cancellation, and inject-and-continue
