# Synapse

> **Coordination + safety layer for multi-agent AI on shared codebases.**
> Audit existing trace exports for silent collisions, prevent them live, resolve them with your own LLM.

---

## In 60 seconds

```bash
pip install synapse-protocol
synapse audit ./traces.json
```

Auto-detects trace formats: OpenInference, LangSmith, AWS Bedrock Agents, GCP Vertex Agent Builder, Azure AI Agent Service, plain JSONL.

[**Try the hosted audit tool →**](https://github.com/arajgor1/synapse/tree/main/launch/hosted-audit) (drop a trace JSON in your browser, no install)

---

## What problem this solves

Two AI agents on the same codebase will silently overwrite each other and quietly disagree on the schema. Your existing tools don't catch it:

| Tool | What it catches | What it misses |
|---|---|---|
| **Git** | Textual file conflicts (loud markers) | Belief divergence: alice picks `/api/login`, bob picks `/auth/login` — different files, both PRs green, production 500s |
| **CI** (pytest, etc.) | Type errors, broken tests | Cross-PR semantic drift that doesn't break tests |
| **LangSmith / Phoenix / Langfuse** | Trace storage + visualization | Cross-agent conflict analysis (their roadmap, our purpose) |
| **MCP / A2A** | Agent ↔ tool / agent ↔ agent transport | Coordination + audit |

Synapse sits across these and catches what they miss.

---

## Empirically validated

### AgenticFlict benchmark
**F1 = 0.865** on 5,408 paired PRs from the public 142,652-PR dataset (5 agents: Copilot, Cursor, Devin, Claude Code, OpenAI Codex). 100% recall.

[See per-agent breakdown →](benchmarks/agenticflict.md)

### Real two-Claude-Code session
**21 conflicts on 7 files** — coherence 0.80 — between two real `claude -p` headless sessions on the same Stripe-Lite repo.

### Multi-orchestrator vs all alternatives
| Strategy | Silent file loss | Belief divergences caught |
|---|---|---|
| No coordination | 4 of 8 | 0 of 3 |
| Git branches + naive merge | 0 (loud markers instead) | **0 of 3** |
| PR + CI w/ pytest | 3 | **1 of 3** |
| Shared coord.md | 2 | 0 |
| **Synapse auto_merge** | **0** | **3 of 3** |

[Full empirical case →](benchmarks/multi-orchestrator.md)

---

## Pick your install path

- **Solo dev with concurrent agents** (Cursor + Claude Code in tmux) → [Solo dev guide](for-solo-devs.md)
- **Small team with PR-based workflow** → [Small team guide](for-small-teams.md)
- **Enterprise on cloud agent stacks** (Bedrock / Vertex / Azure) → [Enterprise guide](for-enterprises.md)

Or skip ahead to the [install instructions](guide/install.md).

---

## Honest about prior art

Synapse is an open-source production-grade implementation in the **semantic-consensus** category formalized by Vivek Acharya ([arXiv 2604.16339](https://arxiv.org/abs/2604.16339), March 2026). We share his conflict taxonomy and resolution-tier model.

We differ in three ways:
1. **Audit on existing trace exports** — no middleware deployment, no agent-runtime patching
2. **FS-watcher path for IDE / CLI agents** — covers Cursor, Claude Code, Codex CLI, VS Code
3. **Real-published-SDK regression gate** — 6 of 8 adapters confirmed working against current published packages

[Full SCF comparison →](prior-art/scf.md)
