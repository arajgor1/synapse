# ADR-0001: v1.0 Architecture Baseline

**Status:** Accepted
**Date:** 2026-05-06
**Deciders:** Aadit Rajgor

## Context

Synapse v1.0 unifies two earlier design rounds (v0.1 system design and v0.2 inference-aware adaptations) into a single locked spec. This ADR records the architectural baseline that all subsequent ADRs build on.

## Decision

The v1.0 architecture is locked with the following components and choices:

### Components

1. Protocol — 8 message types, JSON Schema, ULID-keyed envelope
2. Message Bus — Redis Streams
3. State Graph — Postgres with JSONB, GIN-indexed scope[]
4. Router — three layers: L1 rules, L2 SQL conflict, L3 Haiku semantic
5. Coordinator — Sonnet-class agent, event-driven
6. SDK — Python first (TypeScript month 8), decorator-based
7. Inference Adapter Layer — three tiers: Native / Local-API / Hosted
8. Observability UI — Next.js + WebSockets
9. Benchmark CLI — `synapse bench`

### Key Mechanisms

- **Append-and-continue** is the primary mid-stream injection mechanism (not cancel-and-restart). Preserves KV cache, ~1.05x overhead on native backends.
- **Three-tier urgency** (low / medium / high) determines whether signals consume at decision points, inject mid-stream, or trigger pre-execution gates.
- **Backend-aware routing**: hosted-agent injection thresholds raised dynamically based on cost telemetry (COST_REPORT messages).
- **Multi-tenant isolation specified in adapter contract from day one**: `process` mode in v1.0, `request_id` in v1.1.

### Resolved Open Questions

| Question | Decision |
|---|---|
| Backend benchmark tool | Ship in v1 — `synapse bench` with three standard workloads |
| Streaming partial-output preservation | Per-provider cancel handlers; fallback to full restart for inconsistent providers |
| Reasoning-model backends | `is_reasoning_model: true` flag; signals queue during thinking phase |
| Multi-tenant self-hosted isolation | Specified in adapter contract; v1.0 ships `process` mode |

## Consequences

**Becomes easier:**
- Implementing new backends: clear adapter contract with capability declarations
- Reasoning about coordination cost: COST_REPORT messages provide ground truth
- Onboarding new contributors: protocol-first design means the spec is the reference

**Becomes harder:**
- Changing protocol semantics post-v1.0: requires major version bump and migration window
- Adding new urgency tiers: would ripple through router, SDK, and adapter contracts

**Will need to revisit:**
- vLLM KV append API stability (track upstream changes)
- L3 router cost as session volume grows (may need tiered Haiku/rules hybrid)
- Whether reasoning-model mid-thinking injection becomes possible (track provider API evolution)

## Action Items

1. [x] Lock the eight message schemas
2. [x] Lock the InferenceAdapter interface
3. [x] Lock the BackendCapabilities schema
4. [ ] Phase 1: SDK skeleton + bus + state graph + L1/L2 router + mocked-backend conflict demo
5. [ ] Phase 2: Hosted adapter (Anthropic) + L3 semantic router

## Revision Notes

- **2026-05-06**: Added CONFLICT as 8th message type. Earlier draft referenced CONFLICT in the INTENTION schema description but did not define it as a payload type. Spec inconsistency caught during external review and resolved before any implementation depended on it.
- **2026-05-06**: Phase 1 scope narrowed to mocked-backend end-to-end demo (was: Anthropic adapter). Real adapter slips to Phase 2 to accelerate proof-of-protocol.
