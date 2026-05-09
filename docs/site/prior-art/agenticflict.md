# AgenticFlict (Allamanis et al., 2026)

[arXiv 2604.03551](https://arxiv.org/abs/2604.03551) · [Zenodo 19396917](https://zenodo.org/records/19396917)

Public dataset of 142,652 real merge conflicts from PRs opened by 5 production AI coding agents (GitHub Copilot, Cursor, Devin, Claude Code, OpenAI Codex). 29,609 of those PRs (20.76%) had textual git conflicts when merged against main.

License: CC BY 4.0.

Synapse uses this as the canonical external benchmark — see [the AgenticFlict benchmark page](../benchmarks/agenticflict.md) for per-agent F1 numbers.

**The dataset paper publishes no algorithmic baseline numbers — Synapse's F1 = 0.865 is therefore the SOTA-by-default for this benchmark's scope-overlap subtask.**
