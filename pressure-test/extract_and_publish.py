"""Local driver: after the Modal pressure-test run completes, this script:

  1. Reads the saved Modal JSON output (bench/results/public_benchmark_*.json)
  2. Parses the artifact-dump section to recover the full
     /tmp/pressuretest/ tree (per-framework artifacts)
  3. Writes each framework's bundle to pressure-test/runs/{framework}/
  4. Builds a per-framework GitHub repo skeleton at
     pressure-test/repos/{framework}-autoapply/
  5. (Optional) Creates a private GitHub repo via `gh repo create` and
     pushes the skeleton.

The script is idempotent — re-running it overwrites the local skeleton
but does not delete or repush an existing GitHub repo without --force-push.
"""
from __future__ import annotations

import argparse, json, os, re, shutil, subprocess, sys, textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
PRESSURE_TEST = REPO_ROOT / "pressure-test"


# ---------------------------------------------------------------------------
# Extract Modal artifact-dump into per-framework dirs
# ---------------------------------------------------------------------------
FILE_BLOCK_PATTERN = re.compile(
    r">>>>>>>>>> FILE: (\S+)\s+\(\d+ bytes\) <<<<<<<<<<\n(.*?)\n<<<<<<<<<< END \1 <<<<<<<<<<",
    re.DOTALL,
)


def extract_artifacts(modal_json_path: Path, runs_dir: Path) -> dict:
    print(f"reading Modal output: {modal_json_path}")
    data = json.loads(modal_json_path.read_text(encoding="utf-8"))
    stdout = data.get("stdout", "")
    matches = FILE_BLOCK_PATTERN.findall(stdout)
    print(f"  found {len(matches)} file blocks in stdout")

    runs_dir.mkdir(parents=True, exist_ok=True)
    by_framework: dict = {}
    for rel_str, body in matches:
        rel = Path(rel_str.replace("\\", "/"))
        # First path segment is the framework name (or "master_summary.json" at the root)
        if "/" in rel.as_posix():
            fw, *_ = rel.parts
        else:
            fw = "_root"
        out_file = runs_dir / rel
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(body, encoding="utf-8")
        by_framework.setdefault(fw, []).append(str(rel))

    print(f"  extracted into: {runs_dir}")
    for fw, files in sorted(by_framework.items()):
        print(f"    {fw}: {len(files)} files")
    return by_framework


# ---------------------------------------------------------------------------
# Build per-framework repo skeleton
# ---------------------------------------------------------------------------
def build_repo_skeleton(framework: str, runs_dir: Path, repos_dir: Path) -> Path:
    repo_dir = repos_dir / f"{framework}-autoapply"
    if repo_dir.exists():
        shutil.rmtree(repo_dir)
    repo_dir.mkdir(parents=True)

    src = PRESSURE_TEST
    # Copy shared + this framework's orchestrator + the runs dir
    (repo_dir / "app").mkdir()
    for f in ("__init__.py", "spec.py", "jobs.py", "scrub.py",
              "runner_base.py", "master_resume.txt"):
        src_path = src / "shared" / f
        if src_path.exists():
            shutil.copy(src_path, repo_dir / "app" / f)
    (repo_dir / "app" / "orchestrators").mkdir()
    (repo_dir / "app" / "orchestrators" / "__init__.py").write_text("", encoding="utf-8")
    helpers = src / "orchestrators" / "_template_helpers.py"
    if helpers.exists():
        shutil.copy(helpers, repo_dir / "app" / "orchestrators" / "_template_helpers.py")
    orch = src / "orchestrators" / f"{framework}_orchestrator.py"
    if orch.exists():
        shutil.copy(orch, repo_dir / "app" / "orchestrators" / f"{framework}_orchestrator.py")

    # Copy runs/{framework}/ → runs/ in repo
    runs_src = runs_dir / framework
    if runs_src.exists():
        shutil.copytree(runs_src, repo_dir / "runs")

    # README
    summary_path = repo_dir / "runs" / "summary.json"
    summary = {}
    if summary_path.exists():
        try: summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception: summary = {}
    intents = summary.get("intents_total", 0)
    thoughts = summary.get("thoughts_total", 0)
    conflicts = summary.get("conflicts_total", 0)
    injections = summary.get("injections_detected", 0)
    elapsed = summary.get("elapsed_s", 0.0)

    findings = render_findings(framework, summary)
    (repo_dir / "runs" / "findings.md").write_text(findings, encoding="utf-8")

    readme = textwrap.dedent(f"""\
        # {framework}-autoapply — Synapse pressure test

        **Status:** test artifact (private repo).
        Owner: [@arajgor1](https://github.com/arajgor1)
        License: Apache 2.0

        This repo is one of 11 in the Synapse v0.2.9 pressure-test campaign.
        Each repo builds the same autoapply pipeline using ONE Synapse
        framework adapter end-to-end, so the 11 runs can be compared on the
        five Synapse pillars (Audit · Observability · Conflict · Intent · NLA).

        ## What this run did

        * **Framework:** `{framework}`
        * **Workload:** 6-step autoapply pipeline (resume parse → role match
          → prompt-injection scrub → cover letter draft → application
          validation → mock ATS submission)
        * **Elapsed:** {elapsed:.1f}s
        * **INTENTIONs persisted:** {intents}
        * **THOUGHT envelopes captured:** {thoughts}
        * **CONFLICTs fired (S4↔S5 scope overlap):** {conflicts}
        * **Prompt-injection payloads detected + stripped:** {injections}

        Full per-pillar scorecard in [`runs/findings.md`](runs/findings.md).

        ## Run artifacts

        ```
        runs/
        ├── envelopes.jsonl              ← full Synapse audit log
        ├── resume_parsed.json           ← structured resume (real LLM)
        ├── matched_roles.json           ← ranked top-5 jobs (real LLM)
        ├── scrub_report.json            ← prompt-injection detections
        ├── cover_letters/*.md           ← drafted letters (real LLM)
        ├── validated_application.json
        ├── submission_results.json      ← mock ATS submission ack
        ├── summary.json                 ← machine-readable summary
        └── findings.md                  ← per-pillar Synapse scorecard
        ```

        ## Reproduce

        ```bash
        pip install synapse-protocol-py[live]
        # plus framework-specific package (see app/orchestrators/{framework}_orchestrator.py)
        export SYNAPSE_REDIS_URL=redis://localhost:6379/0
        export SYNAPSE_POSTGRES_DSN=postgresql://synapse:synapse_dev@localhost:5432/synapse
        export OPENAI_API_KEY=...
        python -m app.orchestrators.{framework}_orchestrator
        ```

        ## Why this exists

        Synapse v0.2.9 ships 11 framework adapters. Without a non-trivial
        cross-framework workload, it's hard to know which adapters fire
        cleanly under realistic dispatch patterns. The 11 repos in this
        campaign each run the same pipeline on a different adapter to
        produce comparable data on:

        * which adapters fire INTENTIONs on every dispatch path,
        * which capture THOUGHT envelopes naturally (Anthropic native
          thinking, OpenAI native reasoning, PSEUDO_THOUGHT fallback),
        * which fire L2 router CONFLICTs when two agents target the
          same scope,
        * which catch prompt-injection payloads via the shared scrubber,
        * and how much wall-clock overhead each adds.

        This is internal pressure-test data; the campaign synthesis lives
        at https://github.com/arajgor1/synapse/blob/main/pressure-test/SYNTHESIS.md.
        """)
    (repo_dir / "README.md").write_text(readme, encoding="utf-8")

    # LICENSE (Apache 2.0 header pointer, not full text)
    (repo_dir / "LICENSE").write_text(
        "Apache License 2.0 — see https://www.apache.org/licenses/LICENSE-2.0\n",
        encoding="utf-8")
    # .gitignore
    (repo_dir / ".gitignore").write_text(
        "__pycache__/\n*.pyc\n.venv/\nnode_modules/\n.env\n", encoding="utf-8")
    # pyproject for the orchestrator (so the repo is self-contained)
    pyproj = textwrap.dedent(f"""\
        [project]
        name = "{framework}-autoapply"
        version = "0.1.0"
        description = "Synapse pressure-test #N — autoapply pipeline via {framework} adapter"
        requires-python = ">=3.11"
        dependencies = [
            "synapse-protocol-py[live]>=0.2.9",
            "openai>=1.0",
        ]
        """)
    (repo_dir / "pyproject.toml").write_text(pyproj, encoding="utf-8")
    return repo_dir


def render_findings(framework: str, summary: dict) -> str:
    """Per-framework 5-pillar scorecard."""
    intents = summary.get("intents_total", 0)
    intents_resolved = summary.get("intents_resolved", 0)
    thoughts = summary.get("thoughts_total", 0)
    conflicts = summary.get("conflicts_total", 0)
    injections = summary.get("injections_detected", 0)
    fingerprints = summary.get("fingerprints_laundered", 0)
    elapsed = summary.get("elapsed_s", 0.0)
    steps = summary.get("steps", [])
    notes = summary.get("notes", [])
    error = summary.get("error", "")

    def pct(n, d): return f"{(100.0*n/d):.0f}%" if d else "—"

    pillar_scores = textwrap.dedent(f"""
        ## Synapse 5-pillar scorecard for `{framework}`

        | Pillar | Score | Evidence |
        |---|---|---|
        | **Audit** | {('✅ pass' if intents > 0 else '❌ no envelope log')} | `runs/envelopes.jsonl` contains {intents} INTENTION rows |
        | **Observability** | {('✅ pass' if intents >= 6 else '⚠️ partial')} | Expected 6+ intents (one per step); got {intents}. Resolution rate: {pct(intents_resolved, intents)} |
        | **Conflict** | {('✅ pass' if conflicts >= 1 else '⚠️ none fired')} | S4↔S5 scope-overlap should fire ≥1 CONFLICT; saw {conflicts} |
        | **Intent** | {('✅ pass' if intents == intents_resolved else '⚠️ orphan intents')} | {intents}/{intents_resolved} INTENTIONs resolved |
        | **NLA (reasoning)** | {('✅ pass' if thoughts >= 1 else '⚠️ no THOUGHTs')} | {thoughts} THOUGHT envelopes captured via `wrap_openai_for_thoughts` |
        """)

    steps_table = "\n".join(
        f"| {s.get('step', '?')} | `{s.get('role', '?')}` | {s.get('intention_id', '')[:14]} | {s.get('elapsed_s', 0):.2f}s | {s.get('has_conflicts')} | {s.get('output_bytes', 0)}B |"
        for s in steps
    )
    if not steps_table.strip():
        steps_table = "| — | — | — | — | — | — |"

    return textwrap.dedent(f"""\
        # `{framework}` — pressure-test findings

        Run took **{elapsed:.1f}s** wall.
        {'**RUN FAILED:** ' + error if error else ''}

        {pillar_scores}

        ## Step-by-step

        | Step | Role | Intent ID (truncated) | Wall | Conflicts | Output bytes |
        |---|---|---|---|---|---|
        {steps_table}

        ## Scrub layer

        * Prompt-injection payloads detected + stripped: **{injections}**
        * AI-fingerprint launder count: **{fingerprints}**

        ## Friction notes (free-form, what was awkward)

        {chr(10).join('* ' + n for n in notes) if notes else '_None._'}

        ## How to read these numbers

        * **CONFLICTs > 0** is the goal here, not zero. The workload is
          designed to make S4 (drafter) and S5 (validator) compete on the
          same scope so the L2 router fires `scope_overlap`. If you see 0,
          either the adapter didn't register the intent fast enough or the
          framework's dispatch path isn't visible to Synapse.
        * **Resolution rate = 100%** means every INTENTION fired in an
          `async with` block exited cleanly (success or explicit failure).
          Anything less means a step crashed mid-flight.
        * **THOUGHT envelopes ≥ 1** confirms `wrap_openai_for_thoughts`
          fires its `PSEUDO_THOUGHT` fallback (since `gpt-4o-mini` has no
          native `reasoning` field).
        """)


# ---------------------------------------------------------------------------
# GitHub push
# ---------------------------------------------------------------------------
def push_to_github(framework: str, repo_dir: Path, *, visibility: str = "private",
                  force: bool = False) -> str:
    """Create the GitHub repo (idempotent) and push.

    Returns the repo URL on success.
    """
    repo_name = f"{framework}-autoapply"
    # Check existence
    r = subprocess.run(["gh", "repo", "view", f"arajgor1/{repo_name}"],
                      capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  creating GitHub repo arajgor1/{repo_name} ({visibility})...")
        subprocess.check_call(
            ["gh", "repo", "create", f"arajgor1/{repo_name}",
             f"--{visibility}", "--description",
             f"Synapse pressure test #11/{framework} — autoapply via {framework} adapter"],
            cwd=repo_dir,
        )
    else:
        print(f"  repo arajgor1/{repo_name} exists; reusing")

    # Init local git, add origin, push
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo_dir, check=False)
    subprocess.run(["git", "remote", "remove", "origin"], cwd=repo_dir, check=False)
    subprocess.run(
        ["git", "remote", "add", "origin",
         f"https://github.com/arajgor1/{repo_name}.git"],
        cwd=repo_dir, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True)
    # CRLF warnings are fine
    subprocess.run(
        ["git", "commit", "-m",
         f"Synapse pressure test for {framework} — autoapply run + audit bundle"],
        cwd=repo_dir, check=False,
        env={**os.environ, "GIT_COMMITTER_NAME": "Aadit Rajgor",
             "GIT_COMMITTER_EMAIL": "aadityarajgor27@gmail.com",
             "GIT_AUTHOR_NAME": "Aadit Rajgor",
             "GIT_AUTHOR_EMAIL": "aadityarajgor27@gmail.com"})
    push_cmd = ["git", "push", "-u", "origin", "main"]
    if force: push_cmd.append("--force")
    subprocess.run(push_cmd, cwd=repo_dir, check=True)
    return f"https://github.com/arajgor1/{repo_name}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--modal-json", type=Path, required=True,
                  help="path to Modal bench/results/public_benchmark_*.json")
    p.add_argument("--skip-push", action="store_true",
                  help="build local repos but do not create/push to GitHub")
    p.add_argument("--visibility", choices=["private", "public"], default="private")
    p.add_argument("--force-push", action="store_true")
    p.add_argument("--frameworks", type=str, default="",
                  help="comma-separated subset to process (default: all)")
    args = p.parse_args()

    runs_dir = PRESSURE_TEST / "runs"
    repos_dir = PRESSURE_TEST / "repos"
    repos_dir.mkdir(exist_ok=True)

    by_fw = extract_artifacts(args.modal_json, runs_dir)
    frameworks = [f for f in by_fw.keys() if f != "_root"]
    if args.frameworks:
        wanted = {x.strip() for x in args.frameworks.split(",")}
        frameworks = [f for f in frameworks if f in wanted]

    pushed = {}
    for fw in frameworks:
        print(f"\n=== framework: {fw} ===")
        repo_dir = build_repo_skeleton(fw, runs_dir, repos_dir)
        print(f"  built local repo at: {repo_dir}")
        if args.skip_push:
            continue
        try:
            url = push_to_github(fw, repo_dir, visibility=args.visibility,
                                force=args.force_push)
            pushed[fw] = url
            print(f"  pushed: {url}")
        except subprocess.CalledProcessError as e:
            print(f"  push failed: {e}")

    print(f"\n=== summary ===")
    print(f"local repos in:   {repos_dir}")
    if pushed:
        print(f"GitHub repos created:")
        for fw, url in pushed.items():
            print(f"  {fw:14s} -> {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
