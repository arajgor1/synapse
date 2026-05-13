# AgenticFlict benchmark for Synapse

Benchmarks Synapse's scope-overlap detector on a real public dataset of
AI-coding-agent merge conflicts.

## Dataset

- **Paper:** [arXiv 2604.03551](https://arxiv.org/abs/2604.03551) — "AgenticFlict: A Large-Scale Dataset of Merge Conflicts in AI Coding Agents Pull Requests on GitHub", AIware 2026 (Montreal).
- **DOI:** [10.5281/zenodo.19396917](https://zenodo.org/records/19396917)
- **License:** CC BY 4.0 (attribution required if you redistribute or build on it)
- **Code:** https://github.com/unlv-evol/AgenticFlict
- **Size:** 142,652 PRs · 29,609 conflicting (20.76%) across 5 agents
  (OpenAI Codex, Copilot, Devin, Cursor, Claude Code) and 47,871 repos.

The raw 149 MB tar.gz unpacks to ~700 MB of CSV — **not committed** to
this repo (see `.gitignore`).

## Download

```bash
cd bench/agenticflict/
curl -L -o AgenticFlict.tar.gz "https://zenodo.org/records/19396917/files/AgenticFlict.tar.gz"
tar -xzf AgenticFlict.tar.gz
```

## Run the benchmark

```bash
pip install pandas
python bench/agenticflict/run_benchmark.py
```

Takes ~30 seconds on a single CPU. No LLM, no Modal, $0.

## Latest results (Synapse v0.2.8)

See `bench/results/agenticflict_benchmark.json` for the full output.
Headline: **F1 = 0.865, recall = 1.000, precision = 0.763** on 5,408
paired PRs (408 same-repo file-overlap positives + 5,000 different-repo
negatives).

Per-agent F1:
- Claude Code: 1.000
- Cursor: 0.970
- Copilot: 0.940
- Devin: 0.944
- OpenAI Codex: 0.786

## Methodology + caveats

This is a **structural** benchmark — it tests Synapse's scope-overlap
detector by synthesizing one Synapse `edit_file` event per file each PR
touched and checking whether Synapse predicts the conflict label that
git would have raised.

What it tests:
- Scope-overlap detection on real (not hand-crafted) agent-PR data
- Per-agent F1 across 5 production AI-coding agents

What it does NOT test:
- Synapse's BELIEF-divergence detection (needs different data shape)
- The live runtime's blocking / merging behavior
- The SCF-aligned policy/capability tier hints

For a higher-fidelity evaluation including the LLM-mediated paths,
re-run the multi-orchestrator benchmark from `bench/results/v02_pitch_phase1/`.

## Citation

If you use this benchmark, please cite both Synapse and AgenticFlict.

```bibtex
@misc{agenticflict2026,
  title  = {AgenticFlict: A Large-Scale Dataset of Merge Conflicts in
            AI Coding Agents Pull Requests on GitHub},
  year   = {2026},
  doi    = {10.5281/zenodo.19396917},
  eprint = {2604.03551},
  archivePrefix = {arXiv},
}
```
