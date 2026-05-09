# AgenticFlict benchmark

**F1 = 0.865** on 5,408 paired PRs from the public 142,652-PR dataset (5 agents: Copilot, Cursor, Devin, Claude Code, OpenAI Codex). 100% recall.

| Agent | F1 | Precision | Recall | n pairs |
|---|---|---|---|---|
| Claude Code | 1.000 | 1.000 | 1.000 | 100 |
| Cursor | 0.970 | 0.941 | 1.000 | 641 |
| Copilot | 0.940 | 0.887 | 1.000 | 1,046 |
| Devin | 0.944 | 0.895 | 1.000 | 648 |
| OpenAI Codex | 0.786 | 0.647 | 1.000 | 8,381 |

Full data: `bench/results/agenticflict_benchmark.json`. Dataset: [arXiv 2604.03551](https://arxiv.org/abs/2604.03551), [Zenodo 19396917](https://zenodo.org/records/19396917).
