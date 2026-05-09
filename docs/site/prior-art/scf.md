# Semantic Consensus Framework (Acharya 2026)

[arXiv 2604.16339](https://arxiv.org/abs/2604.16339) — "Semantic Consensus: Process-Aware Conflict Detection and Resolution for Enterprise Multi-Agent LLM Systems" by Vivek Acharya, March 2026.

This paper formalizes the multi-agent conflict-detection category. Synapse adopts three of its algorithms with citation:

1. **Conflict taxonomy** — Type 1 (Contradictory Intent), Type 2 (Resource Contention), Type 3 (Causal Violation). Synapse maps these to its existing kinds: `scope_overlap`, `stale_base_overwrite`, BELIEF divergence.
2. **Three-tier resolution cascade** — Policy → Capability → Temporal → Escalation. Surfaced on every Synapse conflict as `resolution_tier_hint`.
3. **SAS (Semantic Alignment Score)** — `0.5 * entity_overlap + 0.3 * action_consistency + 0.2 * temporal_alignment`. Computed per agent pair on every audit pass.

Synapse differs from SCF in three ways:

1. **Audit on existing trace exports** — no middleware deployment, no agent-runtime patching, no hand-authored process model required
2. **FS-watcher path** — covers IDE / CLI agents (Cursor, Claude Code, Codex CLI, VS Code) that don't expose live coordination hooks
3. **Real-published-SDK regression gate** — 11 of 11 framework adapters verified against current published packages, not hand-built mocks

SCF's evaluation uses simulated agents; Synapse's uses real Claude Code, real LangGraph, real Anthropic API, real public datasets.
