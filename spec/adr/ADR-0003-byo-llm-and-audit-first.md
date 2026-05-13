# ADR-0003: BYO-LLM, Audit-First Adoption, OpenInference as Trace Substrate

**Status:** Accepted
**Date:** 2026-05-07
**Deciders:** Aadit Rajgor

## Context

After v0.1.0-alpha shipped, we ran two realistic 4-agent product-dev workloads (Instagram-clone backend, data-analysis pipeline) against real Anthropic Haiku 4.5 calls in Modal sandboxes (`runtime/modal/_payloads/real_app_*.py`). Three things became clear:

1. **The original L2 router only caught simultaneous collisions.** Sequential same-resource overwrites — the more common pattern in real multi-agent workflows — slipped through. Fixed in commit `217e7a7` with the `stale_base_overwrite` conflict kind.
2. **Catching collisions ≠ resolving them.** Every CONFLICT we routed was logged and ignored. The integrations had no concept of how to *act* on a conflict.
3. **Detection was structural, not semantic.** Two agents writing different scope names that mean the same thing semantically (`cleaner.revenue_formula = qty*price` vs `analyst.revenue_formula = qty*price*(1-discount)` written to different files) slipped through entirely.

Pressure-testing the v0.1 design against five real personas (solo Claude Code + Cursor user; CrewAI research crew; parallel code reviewers; engineer team with parallel agent sessions; production agent stack) further revealed:

- **Auto-merge is wrong as a default.** Two agents with different system prompts producing a third version nobody reviewed is dangerous, especially in production. The right primitive is *explicit policies* (wait/abort/redirect), with auto-merge as opt-in.
- **Hosted backend is wrong as a default.** Round-trips to a third party gate every agent loop, exposes tool-call payloads to vendors, and adds an SLA dependency. Self-hosted via `docker compose` is the correct default; hosted is a paid convenience for prototyping.
- **Per-framework integrations don't scale.** Every agent framework already emits traces in some standard format. Consuming traces (audit) gets framework-agnosticism for free; emitting envelopes (live) is the upgrade path.

This ADR locks the four strategic decisions for v0.2.

## Decision

### 1. Envelopes remain the canonical wire format

Synapse v1.0's eight envelope types (THOUGHT, INTENTION, PIVOT, BELIEF, BLOCK, CONFLICT, RESOLUTION, COST_REPORT) carry semantics that OpenTelemetry spans do not — `blocking`, `gate_ms`, `expected_outcome`, `confidence`, `evidence`, `suggested_resolution`. We are not flattening to OTel.

Instead, OTel (and LangSmith, JSONL, etc.) are treated as **I/O formats** with two roles:
- **Input:** trace importers normalize external traces into envelopes for audit and live ingestion.
- **Output:** envelope-to-OTel exporters let downstream observability stacks (Phoenix, Arize, Datadog) consume Synapse's data.

This preserves the protocol's expressive power while making Synapse interoperable with the rest of the agent-observability ecosystem.

### 2. Bring-your-own-LLM (BYO-LLM)

Synapse never makes a paid LLM call without the caller's explicit consent. The user's agents already have an LLM (Anthropic / OpenAI / Ollama / Gemini / vLLM / LiteLLM); Synapse's internal reasoning (scope inference, belief divergence, auto-merge, L3 semantic routing) reuses that same model.

Public API:
```python
synapse.set_llm(my_existing_llm_client)
```

If `set_llm()` is never called, Synapse runs in **rules-only mode**:
- L1 router (rules-based): works
- L2 router (SQL conflict detection): works
- L3 router (semantic conflict detection): no-op with log message
- BELIEF divergence: no-op with log message
- Auto-merge: no-op (other policies still work)
- Audit scope inference: rules-only fallback (covers ~70% of cases)

This guarantees Synapse can never surprise-charge a user's account.

### 3. Audit-first adoption

The first user interaction with Synapse is **read-only** on their existing trace data, not live integration. The CLI:

```
$ synapse audit ./langsmith-export.json
Found 23 silent conflicts across 8 sessions. Estimated waste: ~15.4k tokens.
Full report: ./synapse-audit-2026-05-08.html
```

This works with any framework that emits any common trace format. It produces the killer artifact (a stranger's own data showing scary numbers) that converts skeptics in 60 seconds. Live integration is the upgrade path, not the entry point.

### 4. OpenInference-flavored OpenTelemetry as trace substrate

Of the trace formats available (LangSmith proprietary, W&B Weave proprietary, Phoenix open-source via Arize, OpenInference open standard, raw OTel), **OpenInference** is the right bet:

- It's an open standard with growing adoption (LangChain, LlamaIndex, OpenAI SDK, Anthropic SDK, AutoGen)
- It standardizes tool-call span attributes (input/output/name/agent_id) — the data Synapse needs
- Built on top of OTel, so any OTel-emitting framework can be made compatible with minimal effort
- Vendor-neutral; we don't bet our compatibility on one company's product roadmap

LangSmith and raw JSONL importers are also shipped as fallbacks for ecosystems that haven't moved to OpenInference yet.

## Consequences

### Positive

- **Framework compatibility scales without per-framework code.** One importer covers dozens of frameworks via OpenInference; per-framework adapters become opt-in sugar, not the integration substrate.
- **Adoption funnel is much shorter.** `synapse audit` is `pip install` + one command, no Redis/Postgres/router required. Conversion path: audit → install → dashboard → policy enforcement.
- **No surprise costs.** BYO-LLM means Synapse's costs are entirely visible to the user as line items on their existing LLM provider bill. We never aggregate or markup.
- **Privacy by default.** Self-hosted means tool-call payloads never leave the user's infrastructure unless they explicitly opt in to hosted.
- **Future-proof against trace-format churn.** Envelopes are stable; trace importers are swappable. If the industry consolidates on a different format, we add an importer.

### Negative

- **More configuration surface.** `synapse.set_llm()`, `synapse.install()`, `MergePolicy`, `critical_scopes` — more knobs than v0.1's "just import and emit." Mitigation: smart defaults + `synapse.install()` with auto-detection.
- **Cost-attribution complexity.** With BYO-LLM, "how much did Synapse cost me" is not a simple invoice — it's "look at the tagged Synapse calls in your provider's dashboard." Mitigation: COST_REPORT envelopes already exist; surface them in the dashboard.
- **OpenInference is still maturing.** Some span attributes are not standardized (e.g., agent identity in multi-agent traces). Mitigation: ship our own `synapse.attributes.*` namespace as a layer on top, contribute upstream.
- **Backward-compat tax.** Existing v0.1 wrappers (`wrap_tool_call_for_synapse`, `wrapAdapterWithSynapse`, `wrapExtensionWithSynapse`) stay supported. Internal refactor to call `synapse.intend()` is invisible to users but adds a layer.

### Neutral

- **Per-framework adapters become marketing artifacts, not integration code.** They're documented integration paths and worked examples; the actual integration is the universal SDK.
- **The dashboard becomes the front door.** Re-positioning v0.1's UI as the entry point (vs. the protocol being the entry point) shifts the marketing weight without much code change.

## Implementation plan

The 5-week shipping plan that scoped v0.2 has now shipped (v0.2.0 → v0.2.8). See [`CHANGELOG.md`](../../CHANGELOG.md) and the [public roadmap](../../docs/roadmap/) for the current state.

The first PR (week 1) ships:
1. `sdk-python/synapse/audit/` (importers + scope inference + report)
2. `sdk-python/synapse/cli/audit.py` console script
3. 10 fixture trace files (LangGraph, CrewAI, AutoGen, raw OpenAI/Anthropic)
4. Tests asserting each fixture produces expected conflict counts
5. README quickstart: `pip install synapse-audit && synapse audit ./your-traces.json`

## Alternatives considered

### Alt A: Bundle a hosted LLM with Synapse

We considered shipping with a default LLM (e.g., a small hosted model) so users get LLM-mediated features without configuration. Rejected because:
- Adds vendor dependency to a vendor-neutral library
- Creates surprise cost/latency
- Adopters running local-only stacks (Ollama, vLLM) explicitly do not want a network LLM call

### Alt B: Make OTel the canonical wire format

We considered flattening Synapse's envelopes to OTel spans. Rejected because:
- OTel spans don't carry the protocol semantics (`blocking`, `expected_outcome`, etc.)
- Forces lossy translation in both directions
- Couples Synapse's evolution to OTel's

### Alt C: Live-first integration (skip audit)

We considered focusing on live integration only and adding audit later. Rejected because:
- Live integration has 100x the surface area (every framework's hot loop)
- The audit artifact is more compelling to skeptics (their own data, not a benchmark)
- Audit code (importers, scope inference, report) is reusable as live-trace decoders in week 2

## References

- v0.1 launch summary: `README.md`
- Real product-dev test results: `bench/results/real_app_*.json`
- Roadmap (current + shipped): `docs/roadmap/README.md`
- CHANGELOG: `CHANGELOG.md`
- ADR-0001 architecture baseline
- ADR-0002 protocol v1.0 freeze
- OpenInference spec: https://github.com/Arize-ai/openinference
