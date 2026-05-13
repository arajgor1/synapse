# Synapse vs Semantica

**TL;DR: different categories, complementary layers.** This page used to
treat Semantica as Synapse's closest competitor; that framing was based
on an early misread of what Semantica does. The two projects solve
different problems and we recommend using them together.

## What each project actually is

| | Semantica | Synapse |
|---|---|---|
| Category | Knowledge-graph / GraphRAG / ontology-reasoning framework | Multi-agent coordination + audit protocol |
| Primitive | Nodes + edges + SHACL shapes + reasoning engines (forward chaining, Rete, SPARQL) over data | Envelopes (INTENTION, THOUGHT, RESOLUTION, CONFLICT, PIVOT, BELIEF, COST_REPORT) between agents |
| What it replaces | LangChain-RAG / LlamaIndex-retrieval / hand-built vector stores | Per-vendor traces (LangSmith, Phoenix, Helicone) when you need cross-vendor coordination |
| License | MIT | Apache 2.0 |
| Repo | [Hawksight-AI/semantica](https://github.com/Hawksight-AI/semantica) | [arajgor1/synapse](https://github.com/arajgor1/synapse) |

## Use them together

If you have agentic teams that:

1. **Query knowledge graphs** for context (provenance, deduplication, semantic similarity) → **use Semantica** as the context/knowledge layer.
2. **Span multiple vendor SDKs** and need a unified audit log of what each agent intended and did → **use Synapse** as the coordination/audit layer.

The two interfaces don't overlap. A LangGraph agent can pull from a
Semantica context graph and emit Synapse INTENTION envelopes on the same
call — they're addressing different concerns.

## Why this comparison page exists

Some early external blog posts grouped both projects together as
"multi-agent infrastructure." We received PRs asking for a head-to-head
comparison. After looking at both repos carefully, the head-to-head
framing isn't the right one — so this page exists to set the
expectation honestly rather than maintain a confusing scoreboard.

If you need the **head-to-head comparison Synapse does have** — versus
the trace observability tools (LangSmith, Phoenix, Langfuse, Helicone)
that genuinely overlap with Synapse's observability surface — see
[`vs-commercial.md`](vs-commercial.md).

For Synapse's own current capability map, see the README's
[Where Synapse helps section](../../../README.md#where-synapse-helps-and-where-it-doesnt)
or the [public roadmap](../../roadmap/README.md).
