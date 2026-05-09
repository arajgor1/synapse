"""AgenticFlict benchmark — Synapse scope-overlap detector vs ground-truth git conflicts.

Dataset: arXiv 2604.03551, Zenodo DOI 10.5281/zenodo.19396917, CC BY 4.0.

Methodology (structural-only, no LLM):

  1. Load AgenticFlict PR + conflict-files tables (142K PRs, 29,609 conflicting)
  2. Stratified sample: 5K positive pairs (both PRs touched the SAME file in
     the SAME repo, ground-truth conflict) + 5K negative pairs (PRs in
     DIFFERENT repos — guaranteed no real conflict).
  3. For each pair: synthesize a Synapse trace with 2 agents, each emitting
     one edit_file event per file touched. Run synapse audit, check if
     conflict fired.
  4. Compute precision, recall, F1 — overall and per agent (Codex / Copilot /
     Cursor / Devin / Claude_Code).

What this tests: Synapse's scope-overlap detector on a real dataset, not
a hand-crafted sample. NOT a test of belief-divergence or the live runtime.

What it does NOT test: Synapse's policy / capability tier hints, SAS drift
score, or LLM-mediated belief detection — those need different data shapes.

Cost: $0 LLM, ~5 min single-process. No Modal needed.
"""
from __future__ import annotations

import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "sdk-python"))

from synapse.audit.events import AuditEvent
from synapse.audit.scope_inference import annotate_events
from synapse.audit.conflict_detector import detect_conflicts


CDIR = REPO_ROOT / "bench" / "agenticflict" / "AgenticFlict" / "data" / "clean"
N_POSITIVE = 5000
N_NEGATIVE = 5000
SEED = 42


def load_dataset() -> tuple[pd.DataFrame, pd.DataFrame]:
    print("Loading AgenticFlict dataset...")
    pr = pd.read_csv(CDIR / "agenticflict_pr_clean.csv")
    files = pd.read_csv(CDIR / "agenticflict_conflict_files_clean.csv")
    print(f"  PRs: {len(pr):,} (across {pr['agent'].nunique()} agents)")
    print(f"  files: {len(files):,}")
    return pr, files


def build_pair_set(pr: pd.DataFrame, files: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """Construct 5K positive (real-conflict) + 5K negative (different-repo) pairs."""
    rng = random.Random(SEED)

    # POSITIVE PAIRS: For each conflicting PR, find another PR in the same
    # repo that ALSO touched at least one of the same files. These are
    # ground-truth-conflicting pairs.
    print("Building positive pairs (same-repo, file-overlap)...")
    files_by_pr = files.groupby("pr_key").agg({"file_path": list, "agent": "first", "repo_full_name": "first"}).reset_index()
    files_by_pr.columns = ["pr_key", "files", "agent", "repo"]
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for _, row in files_by_pr.iterrows():
        by_repo[row["repo"]].append(row.to_dict())

    positive_pairs = []
    for repo, prs in by_repo.items():
        if len(prs) < 2:
            continue
        # Try all unordered pairs in this repo
        rng.shuffle(prs)
        for i in range(len(prs)):
            for j in range(i + 1, len(prs)):
                a, b = prs[i], prs[j]
                shared = set(a["files"]) & set(b["files"])
                if shared and a["agent"] != b["agent"]:
                    positive_pairs.append({
                        "pr_a": a["pr_key"],
                        "pr_b": b["pr_key"],
                        "agent_a": a["agent"],
                        "agent_b": b["agent"],
                        "files_a": a["files"],
                        "files_b": b["files"],
                        "shared_files": sorted(shared),
                        "label": 1,
                    })
                    if len(positive_pairs) >= N_POSITIVE:
                        break
            if len(positive_pairs) >= N_POSITIVE:
                break
        if len(positive_pairs) >= N_POSITIVE:
            break
    print(f"  positive pairs collected: {len(positive_pairs):,}")

    # NEGATIVE PAIRS: pairs in DIFFERENT repos — guaranteed no real conflict.
    # We use the full PR table (not just conflicting) to draw from a wider pool.
    print("Building negative pairs (different-repo)...")
    pr_with_files = pr[pr["pr_key"].isin(files_by_pr["pr_key"])].copy()
    if len(pr_with_files) < 100:
        pr_with_files = pr.copy()
    sampled = pr_with_files.sample(n=min(20000, len(pr_with_files)), random_state=SEED).to_dict("records")
    files_lookup = {row["pr_key"]: row["files"] for _, row in files_by_pr.iterrows()}

    negative_pairs = []
    rng2 = random.Random(SEED + 1)
    while len(negative_pairs) < N_NEGATIVE and len(sampled) >= 2:
        a = rng2.choice(sampled)
        b = rng2.choice(sampled)
        if a["pr_key"] == b["pr_key"]:
            continue
        if a["repo_full_name"] == b["repo_full_name"]:
            continue
        # Use a stable file list — for non-conflicting PRs we don't have
        # the file table populated, so fall back to a synthetic touch
        files_a = files_lookup.get(a["pr_key"], [f"src/{a['pr_key'].replace('/','_')}.py"])
        files_b = files_lookup.get(b["pr_key"], [f"src/{b['pr_key'].replace('/','_')}.py"])
        negative_pairs.append({
            "pr_a": a["pr_key"],
            "pr_b": b["pr_key"],
            "agent_a": a["agent"],
            "agent_b": b["agent"],
            "files_a": list(files_a)[:20],  # cap to keep events small
            "files_b": list(files_b)[:20],
            "shared_files": [],
            "label": 0,
        })
    print(f"  negative pairs collected: {len(negative_pairs):,}")

    return positive_pairs, negative_pairs


def synthesize_events(pair: dict, base_ts_ms: int = 1_700_000_000_000) -> list[AuditEvent]:
    """One AuditEvent per file each agent touched. Tied to a fake session
    so Synapse groups them together."""
    events = []
    session = f"sess-{pair['pr_a']}-{pair['pr_b']}".replace("/", "_")[:80]
    for i, f in enumerate(pair["files_a"]):
        events.append(AuditEvent(
            trace_id=f"tr-{pair['pr_a']}",
            span_id=f"{pair['pr_a']}#{i}",
            agent_id=f"{pair['agent_a']}_{pair['pr_a']}",
            session_id=session,
            tool_name="edit_file",
            ts_start_ms=base_ts_ms + i * 100,
            ts_end_ms=base_ts_ms + i * 100 + 50,
            tool_args={"path": f},
        ))
    for j, f in enumerate(pair["files_b"]):
        events.append(AuditEvent(
            trace_id=f"tr-{pair['pr_b']}",
            span_id=f"{pair['pr_b']}#{j}",
            agent_id=f"{pair['agent_b']}_{pair['pr_b']}",
            session_id=session,
            tool_name="edit_file",
            # Stagger B's writes after A's so detector treats them as
            # stale-base candidates within the lookback window
            ts_start_ms=base_ts_ms + 10_000 + j * 100,
            ts_end_ms=base_ts_ms + 10_000 + j * 100 + 50,
            tool_args={"path": f},
        ))
    return events


def run_pair(pair: dict) -> tuple[int, int]:
    """Returns (predicted_label, true_label)."""
    events = synthesize_events(pair)
    annotate_events(events)
    conflicts = detect_conflicts(events, lookback_ms=24 * 60 * 60 * 1000, write_only=False)
    return (1 if conflicts else 0, pair["label"])


def main():
    started = time.time()
    pr, files = load_dataset()
    pos, neg = build_pair_set(pr, files)
    print(f"\nTotal pairs: {len(pos) + len(neg):,} ({len(pos):,} positive + {len(neg):,} negative)\n")

    print("Running Synapse scope-overlap detector...")
    tp = fp = tn = fn = 0
    per_agent_pred: dict[str, list[tuple[int, int]]] = defaultdict(list)
    per_agent_pred_b: dict[str, list[tuple[int, int]]] = defaultdict(list)
    t0 = time.time()
    for i, pair in enumerate(pos + neg):
        pred, true = run_pair(pair)
        per_agent_pred[pair["agent_a"]].append((pred, true))
        per_agent_pred_b[pair["agent_b"]].append((pred, true))
        if pred == 1 and true == 1:
            tp += 1
        elif pred == 1 and true == 0:
            fp += 1
        elif pred == 0 and true == 1:
            fn += 1
        else:
            tn += 1
        if (i + 1) % 1000 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            print(f"  {i+1:>6,} / {len(pos)+len(neg):,}  ({rate:.0f}/s)")

    elapsed = time.time() - started
    total = tp + fp + tn + fn
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    accuracy = (tp + tn) / total if total else 0.0

    print("\n=== AgenticFlict scope-overlap benchmark — Synapse v0.2.2 ===")
    print(f"  total pairs:    {total:,}  (pos={tp+fn:,}, neg={tn+fp:,})")
    print(f"  TP: {tp:,}  FP: {fp:,}  TN: {tn:,}  FN: {fn:,}")
    print(f"  precision:      {precision:.4f}")
    print(f"  recall:         {recall:.4f}")
    print(f"  F1:             {f1:.4f}")
    print(f"  accuracy:       {accuracy:.4f}")
    print(f"  elapsed:        {elapsed:.1f}s")

    print("\nPer-agent F1 (when listed agent is one of the pair):")
    fmt = "  {:<14} {:>8} {:>10} {:>10} {:>10}"
    print(fmt.format("agent", "n", "precision", "recall", "F1"))
    # Combine A-side and B-side
    per_agent_combined: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for ag, lst in per_agent_pred.items():
        per_agent_combined[ag].extend(lst)
    for ag, lst in per_agent_pred_b.items():
        per_agent_combined[ag].extend(lst)
    for agent, results in sorted(per_agent_combined.items()):
        a_tp = sum(1 for p, t in results if p == 1 and t == 1)
        a_fp = sum(1 for p, t in results if p == 1 and t == 0)
        a_fn = sum(1 for p, t in results if p == 0 and t == 1)
        a_p = a_tp / (a_tp + a_fp) if (a_tp + a_fp) else 0.0
        a_r = a_tp / (a_tp + a_fn) if (a_tp + a_fn) else 0.0
        a_f = 2 * a_p * a_r / (a_p + a_r) if (a_p + a_r) else 0.0
        print(fmt.format(agent, len(results), f"{a_p:.3f}", f"{a_r:.3f}", f"{a_f:.3f}"))

    out = {
        "dataset": "AgenticFlict v1 (zenodo 19396917)",
        "synapse_version": "0.2.2-pre",
        "n_pairs": total,
        "n_positive": tp + fn,
        "n_negative": tn + fp,
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": accuracy,
        "elapsed_seconds": elapsed,
        "per_agent": {
            agent: {
                "n": len(results),
                "tp": sum(1 for p, t in results if p == 1 and t == 1),
                "fp": sum(1 for p, t in results if p == 1 and t == 0),
                "fn": sum(1 for p, t in results if p == 0 and t == 1),
                "tn": sum(1 for p, t in results if p == 0 and t == 0),
            }
            for agent, results in per_agent_combined.items()
        },
        "methodology": (
            "Structural scope-overlap test. For each pair of PRs, "
            "synthesized 2 Synapse agents emitting edit_file events for "
            "the files each PR touched. Positive label = same-repo + "
            "shared file. Negative label = different repo (guaranteed "
            "no conflict). Synapse's scope-overlap detector predicts "
            "conflict iff the two agents' edit_file scopes overlap. "
            "No LLM, no Modal."
        ),
    }
    out_path = REPO_ROOT / "bench" / "results" / "agenticflict_benchmark.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nSaved -> {out_path}")


if __name__ == "__main__":
    main()
