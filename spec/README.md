# Synapse Protocol Specification

This directory holds the protocol artifacts that any Synapse implementation must conform to. The protocol is the durable contract; runtime, SDK, and adapters are implementations of it.

## Layout

```
spec/
├── protocol-v1.0/
│   ├── envelope.schema.json              The wrapper around every message
│   ├── agent_registration.schema.json    Agent connect handshake
│   ├── intention.schema.json             Pre-action declaration
│   ├── thought.schema.json               Streaming reasoning
│   ├── pivot.schema.json                 Direction change mid-task
│   ├── belief.schema.json                World-model assertion
│   ├── block.schema.json                 Stuck, need help
│   ├── resolution.schema.json            Action completed
│   └── cost_report.schema.json           Token/wall-clock cost telemetry
└── adapter.md                            InferenceAdapter contract
```

## The Seven Message Types

| Type | When emitted | Default routing |
|---|---|---|
| THOUGHT | Streaming reasoning, throttled | Coordinator + L3 router only |
| INTENTION | Before any tool call or major step | Conflict-checked, broadcast on overlap |
| PIVOT | Plan changes mid-task | Routed to anyone affected |
| BELIEF | World-model assertion | Diffed against others' beliefs |
| BLOCK | Stuck, need help | Coordinator + capable agents |
| RESOLUTION | After tool call completes | Routed to dependents |
| COST_REPORT | After signal handled | Coordinator (telemetry) |

## Versioning

- **Minor versions are additive.** New optional fields, new message types. Old consumers must ignore unknown fields.
- **Major versions require migration.** Producers may emit both old and new during a transition window (default: 6 months).
- **Experimental message types use the `x-` prefix** (e.g., `x-WHISPER`). Promoted to standard via versioned spec update.

## Validation

All implementations MUST validate every message against the appropriate schema before publishing to the bus. Invalid messages are dropped with a logged error and never reach consumers.

## Reading Order

If you're new to the protocol, read in this order:

1. `envelope.schema.json` — what every message looks like
2. `intention.schema.json` — the most important message; drives all conflict detection
3. `agent_registration.schema.json` — how agents declare themselves
4. `adapter.md` — how backends are abstracted
5. The remaining message types in any order
