# Synapse Protocol v1.0

**Status:** Frozen (since 2026-05-06, [ADR-0002](../adr/ADR-0002-protocol-v1.0-freeze.md))
**License:** Apache 2.0
**Reference implementations:** [Python SDK](../../sdk-python/) · [TypeScript SDK](../../sdk-typescript/)

The Synapse protocol is an open standard for **multi-agent coordination + safety semantics**. It defines the on-the-wire envelope format and message types that agents from different frameworks use to coordinate, detect collisions, and resolve them.

It does *not* compete with [MCP](https://modelcontextprotocol.io) (tool access), [A2A](https://github.com/a2aproject/A2A) (cross-vendor agent comms), or LangSmith / Phoenix / Langfuse (observability). It complements them.

---

## What's in v1.0

The protocol is **eight message types** and **one envelope format**. That's it.

| Schema | Purpose |
|---|---|
| [`envelope.schema.json`](envelope.schema.json) | The wire format. Every message is wrapped in this. |
| [`agent_registration.schema.json`](agent_registration.schema.json) | First message an agent sends — declares identity, scopes_owned, subscribes patterns |
| [`thought.schema.json`](thought.schema.json) | Reasoning trace, no side effects |
| [`intention.schema.json`](intention.schema.json) | "I'm about to do X to scope Y" — the load-bearing message for conflict detection |
| [`pivot.schema.json`](pivot.schema.json) | "I'm changing direction" — fired in response to a CONFLICT |
| [`belief.schema.json`](belief.schema.json) | "I believe key=value with confidence c" — for semantic-conflict detection |
| [`block.schema.json`](block.schema.json) | "I need help" — escalation signal |
| [`conflict.schema.json`](conflict.schema.json) | Detector output — emitted by the L2 router back to the offending agent's inbox |
| [`resolution.schema.json`](resolution.schema.json) | "I'm done" — final state of an INTENTION |
| [`cost_report.schema.json`](cost_report.schema.json) | Token/wallclock telemetry |

---

## Envelope format

Every message wraps the same envelope:

```json
{
  "msg_id": "01HX...",                      // ULID, monotonic, lexicographically sortable
  "type": "INTENTION",                      // one of the 8 message types
  "version": "1.0",                         // protocol version
  "agent_id": "code_reviewer",
  "session_id": "company_42_session_a",
  "task_id": null,                          // optional task grouping
  "parent_msg_id": null,                    // for threading replies/derivations
  "timestamp_ms": 1700000000000,            // ms since epoch
  "tenant_id": null,                        // optional multi-tenant isolation
  "payload": { ... }                        // schema-typed by `type`
}
```

Per-type payloads validate against their respective `*.schema.json`.

---

## INTENTION — the most important message

```json
{
  "msg_id": "01HX...",
  "type": "INTENTION",
  "agent_id": "api_engineer",
  "session_id": "session_a",
  "payload": {
    "action": {"tool": "write_file", "args": {"path": "models/User.js"}},
    "scope": ["repo.fs.models/User.js:w"],
    "expected_outcome": "Add bio + avatar_url fields",
    "blocking": true,
    "estimated_duration_ms": 2000,
    "uncertainty": null,
    "blocks_others": []
  }
}
```

**Scope grammar:** `<namespace>.<path>:<modifier>` where modifier is `r` (read), `w` (write), or `rw`. Two intentions conflict when:
- Their scopes overlap (after normalization), AND
- One of them claims write access, AND
- They're emitted by different agents

Synapse's L2 router runs this check on every INTENTION emit. See [`spec/conflict-semantics.md`](../conflict-semantics.md) for the full matching rules.

---

## CONFLICT — the response

When the router detects an overlap, it emits a CONFLICT to the new intention's agent:

```json
{
  "type": "CONFLICT",
  "agent_id": "router",
  "payload": {
    "intention_id": "01HX...",                    // the offending intention
    "conflicting_intentions": [                    // list of overlapping priors
      {
        "intention_id": "01HW...",
        "agent_id": "db_engineer",
        "scope": ["repo.fs.models/User.js:w"],
        "started_at_ms": 1699999998000
      }
    ],
    "kind": "stale_base_overwrite",                // or "scope_overlap"
    "overlapping_scopes": ["repo.fs.models/User.js:w"],
    "suggested_resolution": "pivot",               // or "wait" / "narrow_scope" / "coordinate" / "abort"
    "rationale": "..."
  }
}
```

What the agent does next is a policy decision (handled by `MergePolicy` in the reference SDKs).

---

## Conflict kinds

| Kind | Trigger | Detection |
|---|---|---|
| `scope_overlap` | Two agents have ACTIVE intentions on overlapping scopes | SQL: `status='active' AND scope && new_scope AND agent_id != new_agent` |
| `stale_base_overwrite` | An agent's intention resolved within the last 60s; another now claims the same scope | SQL with extended lookback window |
| `belief_divergence` | 2+ agents emitted different `value` for the same belief `key` in the same session | SQL on `beliefs` table grouped by key |

The first two are structural (file/scope-level). The third is semantic (concept-level) and fires even when agents wrote to *different* files — useful when, e.g., three agents independently picked three different revenue formulas.

---

## Implementations

| SDK | Repo | Tests | Frameworks |
|---|---|---|---|
| Python | [`sdk-python/`](../../sdk-python/) | 249 | LangGraph, CrewAI, AutoGen, OpenAI Agents SDK, Pydantic AI, smolagents, Hermes |
| TypeScript | [`sdk-typescript/`](../../sdk-typescript/) | 233 | LangGraph.js, Vercel AI SDK, Paperclip, OpenClaw |

Both speak the same envelope wire format, both pass against the JSON Schemas in this directory.

---

## How to add a framework adapter

Three steps:

1. **Hook the framework's tool-dispatch site.** Wrap it in `synapse.intend()` (Python) or `synapse.intendWith()` (TypeScript).
2. **Map the tool call to a scope claim.** Default heuristics handle filesystem (`repo.fs.<path>:w`), shell, HTTP writes, DB writes; override via `scopeFromCall`.
3. **Resolve agent identity.** Pull from framework metadata (e.g. LangGraph's `langgraph_node`, CrewAI's `agent.role`).

The Python and TypeScript SDKs each ship 5-7 reference adapters. Adding a new framework is typically ~80-120 lines.

---

## Governance

**Open changes only.** Protocol changes require a public ADR (Architecture Decision Record) in [`spec/adr/`](../adr/). The current ADRs:

- [ADR-0001](../adr/ADR-0001-architecture-baseline.md) — Architecture baseline
- [ADR-0002](../adr/ADR-0002-protocol-v1.0-freeze.md) — Protocol v1.0 freeze
- [ADR-0003](../adr/ADR-0003-byo-llm-and-audit-first.md) — BYO-LLM + audit-first adoption

No CLA. Apache 2.0. Anyone can fork, anyone can implement. The reference implementations are open-source under the same license.

---

## Validate against the schemas

```bash
pip install synapse-protocol-py
synapse spec validate ./my-envelope.json
```

Or use the `jsonschema` library directly with the files in this directory.

---

## Reference

- Conflict semantics: [`spec/conflict-semantics.md`](../conflict-semantics.md)
- Adapter contract: [`spec/adapter.md`](../adapter.md)
- Positioning: [`spec/positioning.md`](../positioning.md)
- Integrations: [`spec/integrations/`](../integrations/)
- ADRs: [`spec/adr/`](../adr/)
- Reference implementations: [`sdk-python/`](../../sdk-python/), [`sdk-typescript/`](../../sdk-typescript/)
