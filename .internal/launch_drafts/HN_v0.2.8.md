# HN Show post — v0.2.8

## Title (under 80 chars)

```
Show HN: Synapse – audit layer for agentic teams across 10 vendor SDKs
```

Alternatives:
- `Show HN: 10 agentic frameworks built a Flask app together. Here's the audit log.`
- `Show HN: Cross-vendor agentic coordination protocol — 10 SDKs in 1 session`

## URL

```
https://github.com/arajgor1/synapse
```

## Text (the first comment slot — explain it like an HN reader)

```
Synapse is an open-source coordination + audit protocol for AI agent
teams that span multiple vendor SDKs (AutoGen, CrewAI, LangGraph,
smolagents, Agno, LlamaIndex, Pydantic AI, OpenAI Agents SDK, Google ADK,
Hermes).

The problem I built it for: when ten different vendor SDKs collaborate
on one task, no existing trace tool spans them. LangSmith covers
LangChain. Phoenix covers OpenInference. Helicone covers OpenAI calls.
None of them gives you one unified audit log across vendors.

What v0.2.8 ships: a committed bundle in `bench/results/v32_app_bundle/`
that proves the cross-vendor case end-to-end. Ten different agentic
SDKs played ten different roles building one Flask Todo app. The app
runs (`GET /todos → 200`). The audit log (`envelopes.jsonl`) has
INTENTION envelopes from all the participating agents tagged by vendor,
all in one Synapse session.

Reproduce in 10 seconds after clone:

  pip install flask
  cd bench/results/v32_app_bundle
  python -c "import main; print(main.app.test_client().get('/todos').status_code)"
  # → 200

Things I think HN will care about:

* The 10-adapter convergence bench is byte-for-byte deterministic across
  runs (v26 == v27 — 23 intents and 9 THOUGHT envelopes match exactly).
  Most "multi-agent" benchmarks I've seen flap.

* OpenAI THOUGHT-capture parity with Anthropic just landed: when the
  model has no native `reasoning` field (gpt-4o-mini etc.), we now emit
  a PSEUDO_THOUGHT envelope from `message.content` so the audit trail
  is never silent.

* I'm being deliberately upfront about what doesn't work yet:
  - 3 of 10 OpenAI adapters dispatch tools with empty content args
    under gpt-4o-mini (a fallback rescues the artifact but no INTENT
    is registered)
  - HF deep NLA module (logits + attention) ships but Modal image
    doesn't include torch by default

Apache 2.0. v0.2.8 wheel on PyPI. Public benchmark with every
iteration's results: bench/PUBLIC_BENCHMARK.md.

Happy to answer anything — especially "what's the next vendor adapter
you'd want?" I'm reading every comment for the next two hours.
```

## When to post

- **Tuesday or Wednesday, 9:00-10:00 AM ET** (best HN traction window)
- Avoid Friday (drops off the front page over weekend)
- Avoid 1st of month (US holidays cluster)

## Preparation

Before submitting:
1. Make sure `git push origin main` is done (the bundle MUST be visible)
2. Verify the reproduce one-liner works on a fresh clone
3. Have responses pre-drafted for the predictable questions below

## Predictable questions + drafted answers

**Q: How is this different from LangSmith / Phoenix / Helicone?**

A: Those are vendor-specific (or LLM-call-specific) trace tools. They
log the calls one vendor's SDK makes. Synapse is one envelope log
**across vendors** — when an autogen agent and a crewai agent
collaborate on the same task, they appear in the same Postgres
intentions table with the same session_id. LangSmith would show you the
autogen path; Phoenix the crewai path; neither would show you both
side-by-side.

**Q: How is this different from MCP / A2A?**

A: MCP is a tool-access standard (how an agent talks to a tool
provider). A2A is an agent-interop standard (how two agents talk to
each other). Synapse is the audit + coordination layer (what each agent
intended, what it actually did, who conflicted, who pivoted). Different
layers; complementary.

**Q: How is this different from Semantica?**

A: Semantica is a knowledge-graph / GraphRAG / ontology framework —
about representing your data semantically. Synapse is about
coordinating the *agents* that query that data. Different layers,
mostly complementary. (Semantica is great; recommend it if knowledge
graphs are your need.)

**Q: How does the cross-vendor cooperative build actually work?**

A: Each adapter monkey-patches its host SDK's tool-dispatch path
(`FunctionCall.execute` in autogen, `Task.execute` in crewai,
`AgentWorkflow._call_tool` in llama_index, etc.). When a tool fires, an
INTENTION envelope goes to a shared Postgres. The session_id is the
same across all ten adapters. That's how they all end up in one log.

**Q: 0 thoughts captured for 3 adapters — why?**

A: Honest answer in the carry-forward: gpt-4o-mini called the tools
with `content=""` for those three (langgraph/smolagents/agno). The
fallback layer regenerates the artifact, but no INTENT lands for the
failed dispatch. Anthropic models (Sonnet 4.5, Haiku 4.5) don't have
this issue — v27 Anthropic-route got 10/10 with all intents.

**Q: Why not just use OTel?**

A: OTel is one of the trace formats Synapse imports — `synapse audit
./traces.json` auto-detects OTel/OpenInference among 6 trace formats.
But OTel covers *what each call did*, not *what each agent intended*
relative to a shared scope. That's the envelope/audit layer
specifically.

**Q: Latency overhead?**

A: 1.59ms median when no conflict fires (in-process router); higher
when an actual collision is detected and resolved. Full latency
distribution in bench/LATENCY.md.

**Q: Production users?**

A: Honestly, zero today. v0.2.8 is the launch. Looking for design
partners.
