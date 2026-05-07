# ADR-0002: Protocol v1.0 Freeze

**Status:** Accepted
**Date:** 2026-05-06
**Deciders:** Aadit Rajgor

## Context

Synapse v0.1.0 ships with eight protocol message types, an envelope schema, an agent-registration handshake, and the InferenceAdapter contract. These are now in production use across six implementations (Mock, Anthropic, Gemini, OpenAI, Ollama, vLLM-via-Modal) and a runtime (router L1/L2/L3, coordinator, gateway, UI).

Before public release, we lock the wire format. This ADR records the freeze and the rules that govern future protocol evolution.

## Decision

**Protocol v1.0 is frozen as of commit `7656e13`.**

The frozen surface comprises:

- `spec/protocol-v1.0/envelope.schema.json`
- `spec/protocol-v1.0/agent_registration.schema.json`
- `spec/protocol-v1.0/intention.schema.json`
- `spec/protocol-v1.0/thought.schema.json`
- `spec/protocol-v1.0/pivot.schema.json`
- `spec/protocol-v1.0/belief.schema.json`
- `spec/protocol-v1.0/block.schema.json`
- `spec/protocol-v1.0/conflict.schema.json`
- `spec/protocol-v1.0/resolution.schema.json`
- `spec/protocol-v1.0/cost_report.schema.json`
- `spec/adapter.md` — InferenceAdapter contract
- `spec/conflict-semantics.md` — scope grammar + matching rules

## Evolution Rules

### Backward-compatible (allowed in 1.x)

- Adding new optional fields to existing schemas
- Adding new enum values to fields where the spec explicitly says "experimental types use the `x-` prefix"
- Adding new message types under the `x-` prefix
- Promoting an `x-` experimental type to a standard type via a new minor version

### Backward-incompatible (requires 2.0)

- Removing or renaming fields
- Changing field types
- Changing required-ness of fields
- Reordering required fields
- Modifying `MessageType` enum semantics
- Changing the envelope shape

### Migration window

When v2.0 ships, producers MUST emit both v1.0 and v2.0 envelopes for at least 6 months (the deprecation window). Consumers SHOULD accept both during this window. After the window, v1.0 emission may be removed.

## Validation

Implementations MUST validate every envelope against the schema before publishing to the bus. Invalid messages are dropped with a logged error and never reach consumers.

The reference validator ships as `synapse spec validate` (added in this commit).

## Consequences

**Becomes easier:**
- Third-party adapter authors have a stable target
- Multi-version consumers can be written confidently
- Breaking changes have a clear, communicated process

**Becomes harder:**
- Fixing genuine schema bugs requires care to avoid breaking existing producers
- Adding fundamentally new coordination primitives (e.g., a `LOCK` message type) requires either the experimental prefix or a major version

**Tracked tech debt:**
- The Pydantic models in `sdk-python/synapse/messages.py` mirror the JSON schemas, but Pydantic doesn't enforce all schema constraints (e.g., the JSON-Schema `allOf if-then` clause on Resolution requiring `error` when `outcome=failure`). The wire-level validator is the source of truth.

## Action Items

1. [x] Lock the eight schemas (no edits without ADR)
2. [x] Add `synapse spec validate` CLI for end-users
3. [ ] Add a CI step that runs spec validate on every PR
4. [ ] Document the deprecation window publicly in spec/README.md
