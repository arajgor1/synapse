# Graph Report - synapse  (2026-05-06)

## Corpus Check
- 14 files · ~3,368 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 76 nodes · 63 edges · 14 communities (7 shown, 7 thin omitted)
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]

## God Nodes (most connected - your core abstractions)
1. `Synapse` - 11 edges
2. `InferenceAdapter Contract` - 10 edges
3. `Contributing to Synapse` - 6 edges
4. `Synapse Protocol Specification` - 6 edges
5. `ADR-0001: v1.0 Architecture Baseline` - 5 edges
6. `Synapse Python SDK` - 4 edges
7. `Capability Flags` - 4 edges
8. `Decision` - 4 edges
9. `Local development` - 2 edges
10. `Architecture at a glance` - 2 edges

## Surprising Connections (you probably didn't know these)
- None detected - all connections are within the same source files.

## Communities (14 total, 7 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.13
Nodes (14): Architecture at a glance, Author, code:block1 (┌─────────────────────────────────────────────────┐), code:bash (# Install), code:block3 (synapse/), Contributing, Design principles, License (+6 more)

### Community 1 - "Community 1"
Cohesion: 0.18
Nodes (10): code:python (from typing import Protocol, AsyncIterator), Cost Reporting, Failure Modes, Implementing a New Adapter, InferenceAdapter Contract, Interface, Reasoning-Model Behavior, Reference Implementations (+2 more)

### Community 2 - "Community 2"
Cohesion: 0.22
Nodes (8): Action Items, ADR-0001: v1.0 Architecture Baseline, Components, Consequences, Context, Decision, Key Mechanisms, Resolved Open Questions

### Community 3 - "Community 3"
Cohesion: 0.25
Nodes (7): Before opening a PR, code:bash (# Bring up Redis + Postgres), Contributing to Synapse, How to propose a new message type, License, Local development, Repository conventions

### Community 4 - "Community 4"
Cohesion: 0.25
Nodes (7): code:block1 (spec/), Layout, Reading Order, Synapse Protocol Specification, The Seven Message Types, Validation, Versioning

### Community 5 - "Community 5"
Cohesion: 0.29
Nodes (6): code:python (import synapse), code:block2 (synapse/), Module layout (planned), Planned shape, Status, Synapse Python SDK

### Community 6 - "Community 6"
Cohesion: 0.5
Nodes (4): Capability Flags, `multi_tenant_isolation`, `supports_midstream_inject`, `supports_partial_preservation`

## Knowledge Gaps
- **47 isolated node(s):** `Before opening a PR`, `code:bash (# Bring up Redis + Postgres)`, `Repository conventions`, `How to propose a new message type`, `License` (+42 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `InferenceAdapter Contract` connect `Community 1` to `Community 6`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Why does `Capability Flags` connect `Community 6` to `Community 1`?**
  _High betweenness centrality (0.013) - this node is a cross-community bridge._
- **What connects `Before opening a PR`, `code:bash (# Bring up Redis + Postgres)`, `Repository conventions` to the rest of the system?**
  _47 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.13 - nodes in this community are weakly interconnected._