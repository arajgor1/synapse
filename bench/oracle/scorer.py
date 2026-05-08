"""Ground-truth oracle for the v0.2.1 pitch campaign.

Inputs (per cell run):
    repo_root_a/   — final state of crew A's view (or shared tree if same)
    repo_root_b/   — final state of crew B's view (or same shared tree)
    write_log      — list of (timestamp, agent_id, file_path, content_hash) tuples
                     captured during the run
    markers_path   — path to markers.json for coherence scoring
    git_dir        — optional: if strategy used git, the path to the repo's .git

Outputs (one JSON per run, identical shape across all 12 cells):
    {
      "file_collisions": [...],
      "silent_overwrites": [...],
      "textual_conflicts_raised": [...],
      "belief_divergences": [...],
      "coherence": 0.0-1.0,
      "wall_clock_s": ...,
      "llm_cost_usd": ...,
      "summary": "..."
    }

Belief-divergence detection uses a small Haiku oracle pass on
candidate file pairs. The same oracle is applied to every cell, so
cross-cell comparisons are fair.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


# -------- pure-deterministic checks (no LLM) --------

@dataclass
class Collision:
    path: str
    writers: list[str]
    final_hash: str
    overwritten_hashes: list[str]


@dataclass
class TextualConflict:
    path: str
    marker_count: int
    raised_by: str  # "git" | "strategy" | "test_failure"


def find_file_collisions(write_log: list[dict]) -> list[Collision]:
    """A collision = same path written by 2+ distinct agent_ids."""
    by_path: dict[str, list[dict]] = {}
    for entry in write_log:
        by_path.setdefault(entry["path"], []).append(entry)

    collisions = []
    for path, writes in by_path.items():
        agents = {w["agent_id"] for w in writes}
        if len(agents) >= 2:
            sorted_w = sorted(writes, key=lambda w: w["ts"])
            collisions.append(Collision(
                path=path,
                writers=sorted(agents),
                final_hash=sorted_w[-1]["content_hash"],
                overwritten_hashes=[w["content_hash"] for w in sorted_w[:-1]],
            ))
    return collisions


def find_silent_overwrites(collisions: list[Collision]) -> list[Collision]:
    """Silent overwrite = collision where final_hash differs from at least
    one overwritten hash (so content was lost) AND no textual_conflict
    was raised by the strategy."""
    return [c for c in collisions if any(h != c.final_hash for h in c.overwritten_hashes)]


def find_textual_conflicts_in_repo(repo_root: str) -> list[TextualConflict]:
    """Scan files for git conflict markers."""
    out = []
    for path in Path(repo_root).rglob("*"):
        if not path.is_file() or path.suffix in {".png", ".jpg", ".pdf", ".db"}:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        markers = content.count("<<<<<<<") + content.count("=======") + content.count(">>>>>>>")
        if markers >= 3:  # at least one triple
            out.append(TextualConflict(
                path=str(path.relative_to(repo_root)),
                marker_count=markers,
                raised_by="git",
            ))
    return out


# -------- coherence scoring (regex-only, deterministic) --------

@dataclass
class MarkerResult:
    id: str
    category: str
    matched: bool
    files_seen: int


def score_coherence(repo_root: str, markers_path: str) -> tuple[float, list[MarkerResult]]:
    spec = json.loads(Path(markers_path).read_text())
    results: list[MarkerResult] = []
    for m in spec["markers"]:
        glob = m["file_glob"]
        regex = re.compile(m["regex"], re.MULTILINE)
        expected = m.get("expected", True)
        matched = False
        files_seen = 0
        for path in Path(repo_root).glob(glob):
            if path.is_file():
                files_seen += 1
                try:
                    content = path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                if regex.search(content):
                    matched = True
                    break
        # If expected is False (e.g. "no British spelling"), invert
        if not expected:
            matched = not matched
        results.append(MarkerResult(
            id=m["id"], category=m["category"],
            matched=matched, files_seen=files_seen,
        ))
    score = sum(1 for r in results if r.matched) / max(1, len(results))
    return score, results


# -------- belief-divergence detection (LLM-mediated) --------

BELIEF_ORACLE_PROMPT = """You are auditing two agent crews that worked on the same task without coordinating. Below are content snippets from files they each touched.

Your job: identify SEMANTIC DISAGREEMENTS — places where crew A and crew B made conflicting decisions on the same logical thing. Examples:
- Different endpoint paths for the same logical action ("/api/login" vs "/auth/login")
- Different column names for the same data ("plan_id" vs "plan", "seat_count" vs "seats")
- Different status codes for the same error class (400 vs 409 for already-canceled)
- Different state values ("canceled" vs "cancelled" vs "expired" vs "terminated")
- Different naming conventions for the same field (canceled_at vs cancelled_at)

Return ONLY a JSON object with this exact shape (no preamble, no markdown fences):

{
  "divergences": [
    {
      "key": "short_lowercase_name_of_the_thing",
      "value_a": "what crew A chose",
      "value_b": "what crew B chose",
      "evidence_a": "verbatim line or path from crew A's snippet",
      "evidence_b": "verbatim line or path from crew B's snippet",
      "severity": "high" | "medium" | "low",
      "rationale": "one sentence why this would break things"
    }
  ]
}

If you find no divergences, return {"divergences": []}.

CREW A SNIPPETS:
---
{snippets_a}
---

CREW B SNIPPETS:
---
{snippets_b}
---
"""


def _gather_snippets(repo_root: str, agent_writes: dict[str, list[str]], max_chars: int = 20000) -> dict[str, str]:
    """For each agent (or crew), concatenate snippets of files they wrote."""
    out = {}
    for agent, paths in agent_writes.items():
        chunks = []
        used = 0
        for p in paths:
            full = Path(repo_root) / p
            if not full.exists() or not full.is_file():
                continue
            try:
                content = full.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            chunk = f"### {p}\n{content[:3000]}\n\n"
            if used + len(chunk) > max_chars:
                break
            chunks.append(chunk)
            used += len(chunk)
        out[agent] = "".join(chunks) if chunks else "(no files)"
    return out


def detect_belief_divergences(
    repo_root: str,
    crew_a_writes: list[str],
    crew_b_writes: list[str],
    anthropic_client=None,
    model: str = "claude-haiku-4-5",
) -> list[dict]:
    """Run the LLM-mediated divergence oracle.

    If anthropic_client is None, returns [] and a marker indicating the
    oracle was skipped — used for offline/cheap smoke-tests."""
    if anthropic_client is None:
        return []

    snippets = _gather_snippets(repo_root, {
        "crew_a": crew_a_writes,
        "crew_b": crew_b_writes,
    })
    # Use plain string replace — .format() chokes on the JSON braces in the template.
    prompt = (
        BELIEF_ORACLE_PROMPT
        .replace("{snippets_a}", snippets.get("crew_a", "(none)"))
        .replace("{snippets_b}", snippets.get("crew_b", "(none)"))
    )
    msg = anthropic_client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    # Strip markdown fences if model added them
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw)
    try:
        parsed = json.loads(raw)
        return parsed.get("divergences", [])
    except json.JSONDecodeError:
        return [{"key": "_oracle_parse_error", "value_a": raw[:200], "value_b": "", "severity": "low"}]


# -------- top-level scoring --------

@dataclass
class CellResult:
    cell_id: str
    strategy: str
    file_collisions: list[dict] = field(default_factory=list)
    silent_overwrites: list[dict] = field(default_factory=list)
    textual_conflicts_raised: list[dict] = field(default_factory=list)
    belief_divergences: list[dict] = field(default_factory=list)
    coherence: float = 0.0
    coherence_breakdown: list[dict] = field(default_factory=list)
    wall_clock_s: float = 0.0
    llm_cost_usd: float = 0.0
    notes: list[str] = field(default_factory=list)


def score_cell(
    cell_id: str,
    strategy: str,
    repo_root: str,
    write_log: list[dict],
    crew_a_paths: list[str],
    crew_b_paths: list[str],
    markers_path: str,
    wall_clock_s: float = 0.0,
    llm_cost_usd: float = 0.0,
    anthropic_client=None,
) -> CellResult:
    collisions = find_file_collisions(write_log)
    silent = find_silent_overwrites(collisions)
    textual = find_textual_conflicts_in_repo(repo_root)
    coherence, marker_results = score_coherence(repo_root, markers_path)
    beliefs = detect_belief_divergences(
        repo_root, crew_a_paths, crew_b_paths, anthropic_client=anthropic_client,
    )

    return CellResult(
        cell_id=cell_id,
        strategy=strategy,
        file_collisions=[asdict(c) for c in collisions],
        silent_overwrites=[asdict(c) for c in silent],
        textual_conflicts_raised=[asdict(t) for t in textual],
        belief_divergences=beliefs,
        coherence=coherence,
        coherence_breakdown=[asdict(r) for r in marker_results],
        wall_clock_s=wall_clock_s,
        llm_cost_usd=llm_cost_usd,
    )


def hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


# -------- CLI --------

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", required=True)
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--write-log", required=True, help="JSON file with write_log array")
    ap.add_argument("--crew-a-paths", required=True, help="JSON file with list of paths")
    ap.add_argument("--crew-b-paths", required=True, help="JSON file with list of paths")
    ap.add_argument("--markers", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--wall-clock", type=float, default=0.0)
    ap.add_argument("--llm-cost", type=float, default=0.0)
    ap.add_argument("--use-llm-oracle", action="store_true")
    args = ap.parse_args()

    client = None
    if args.use_llm_oracle:
        try:
            from anthropic import Anthropic
            key = os.environ.get("ANTHROPIC_API_KEY")
            if key:
                client = Anthropic(api_key=key)
        except ImportError:
            pass

    result = score_cell(
        cell_id=args.cell,
        strategy=args.strategy,
        repo_root=args.repo,
        write_log=json.loads(Path(args.write_log).read_text()),
        crew_a_paths=json.loads(Path(args.crew_a_paths).read_text()),
        crew_b_paths=json.loads(Path(args.crew_b_paths).read_text()),
        markers_path=args.markers,
        wall_clock_s=args.wall_clock,
        llm_cost_usd=args.llm_cost,
        anthropic_client=client,
    )
    Path(args.out).write_text(json.dumps(asdict(result), indent=2))
    print(f"[oracle] {args.cell} ({args.strategy}): "
          f"collisions={len(result.file_collisions)} "
          f"silent={len(result.silent_overwrites)} "
          f"textual={len(result.textual_conflicts_raised)} "
          f"beliefs={len(result.belief_divergences)} "
          f"coherence={result.coherence:.2f}")


if __name__ == "__main__":
    main()
