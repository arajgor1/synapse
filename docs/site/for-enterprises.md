# Synapse for enterprise (cloud agent stacks)

Your team uses AWS Bedrock Agents, Azure AI Agent Service, or GCP Vertex Agent Builder — possibly a mix. **Synapse audits the trace exports from any of those, vendor-neutral.**

## Why this matters at enterprise scale

| Existing infrastructure | What it covers | What Synapse adds |
|---|---|---|
| **Atlas / Bytebase** | Schema drift across migrations | Cross-PR semantic drift on agent-generated PRs |
| **Pact / Contract testing** | Provider-consumer API contracts | Drift detection without requiring contracts upfront |
| **Type-checked ORMs (SQLAlchemy + mypy, Prisma, Drizzle)** | Column-name typos = compile errors | LLM-specific patterns (flip-flopping field names across runs) |
| **Merge queue (GitHub / Trunk / Mergify)** | Cross-PR test failures | Cross-PR *semantic* drift that doesn't break tests (mocked paths) |
| **AI PR reviewers (CodeRabbit / Greptile)** | Per-PR code review by LLM | Multi-PR aggregate analysis + traceability to agent runs |
| **LangSmith / Langfuse / Phoenix** | Trace storage + visualization | Cross-agent **conflict** analysis on top of those traces |

Synapse is **complementary** to all of the above. It doesn't replace your contract infrastructure; it backfills gaps + catches AI-specific patterns.

---

## What Synapse owns at enterprise scale

### 1. Vendor-neutral cloud trace audit

```bash
synapse audit ./bedrock-trace.json   # AWS Bedrock Agents
synapse audit ./vertex-trace.json    # GCP Vertex Agent Builder
synapse audit ./appinsights.json     # Azure AI Agent Service
```

All formats auto-detected. Same conflict taxonomy across vendors.

### 2. Multi-team / multi-vendor coordination

You have an internal LangGraph crew + a Devin license + a Bedrock Agent service. Synapse audits across all three, the only tool that does.

### 3. Adoption gates that survive technical due-diligence

- **Adapter health gate** (`tests/test_adapter_health.py`) — every adapter is verified against the actual published SDK on every release. No silent shipping of broken adapters.
- **AgenticFlict benchmark** (F1 = 0.865) — first external benchmark in the category. Citable.
- **Forensic testing protocol** — every claim in the README is traceable to a test ID and a result file.

---

## Recommended deployment

### Option A — Audit-only (lowest friction, day 1)

Best for: enterprises that already have Atlas + Pact + a merge queue and want to backfill the AI-specific drift gap.

```yaml
# .github/workflows/synapse-audit.yml
on: [pull_request]
jobs:
  audit:
    steps:
      - uses: actions/checkout@v4
      - uses: arajgor1/synapse-audit-action@v1
        with:
          trace-path: '${{ vars.TRACE_PATH }}'
          fail-on-conflict: false  # comment-only at first
```

Cost: $0 (the action is free). PR comments add a Synapse summary alongside CodeRabbit / Atlas.

### Option B — Live coordination (highest fidelity)

Best for: shops where multiple cloud agents (Bedrock / Devin / internal LangGraph) act on the same repo concurrently and need pre-merge blocking.

```bash
pip install 'synapse-protocol[live]'
synapse up   # local Redis + Postgres via docker-compose
```

```python
import synapse
synapse.install(framework="langgraph",
                merge_policy=synapse.MergePolicy.auto_merge,
                critical_scopes=["billing.*", "prod.deploy.*"],
                emit_beliefs_from_tool_results=True)
```

Now Synapse blocks conflicts mid-flight on critical scopes (billing,
prod-deploy) and auto-merges on others.

### Option C — Streaming dashboard for the platform team

Best for: SRE / platform teams that want a real-time view of agent
collisions across the org.

```bash
python -m synapse.streaming.server --port 8765 --watch /var/log/synapse/team.jsonl
```

Then point the [Team Health dashboard](https://github.com/arajgor1/synapse/tree/main/launch/hosted-audit/team-health.html) at `ws://localhost:8765/`.

---

## Compliance + governance

- **Apache 2.0 license** — no copyleft, safe for enterprise embedding
- **BYO-LLM** — Synapse never sends your traces to a third-party LLM unless you configure it to. The audit pipeline is pure deterministic Python.
- **No telemetry** — Synapse doesn't phone home
- **W3C PROV-O–aligned audit trail** — envelope log is compatible with regulated-industry provenance requirements (see [`spec/protocol-v1.0/`](../../spec/protocol-v1.0/))
- **Self-hostable** — both audit and live runtime
- **Vendor-neutral** — no lock-in to any LLM provider, agent framework, or cloud

---

## What we explicitly DON'T do

So you don't waste cycles evaluating us against the wrong category:

- ❌ **Not an agent framework** — we wrap LangGraph / CrewAI / etc., we don't compete with them
- ❌ **Not a knowledge graph** — we track agent actions, not facts (see [Semantica](https://github.com/Hawksight-AI/semantica) for that)
- ❌ **Not a replacement for Atlas / Pact / contract tests** — we backfill what those don't cover for agent-specific patterns
- ❌ **Not for single-agent flows** — pure overhead, no benefit
- ❌ **Not for runtime production safety** — that's feature flags + circuit breakers + service mesh

---

## Get in touch

Evaluating Synapse for an enterprise deployment? Open a GitHub
[Discussion](https://github.com/arajgor1/synapse/discussions) or email
the maintainer (see [SUPPORT.md](../../SUPPORT.md)) with:

- Number of agents in your stack + which frameworks
- Trace export format (OpenInference / Bedrock / Vertex / Azure / other)
- One specific cross-agent failure you'd like Synapse to catch

A 30-minute audit on a real export shows what Synapse would have caught.
