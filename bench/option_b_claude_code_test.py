"""Option B — Real Claude Code two-session test.

Spawns 2 `claude -p` headless processes in the same Stripe Lite v2 starter
dir, with different SYNAPSE_AGENT_ID values, each given the same task.
Runs an FS watcher to capture writes. After both finish, runs the
ground-truth oracle to score what survived.

This validates whether:
1. FS watcher actually attributes writes to the right agent in real-world
   concurrent Claude Code usage
2. Both Claude Code sessions independently produce the kinds of conflicts
   the multi-orch run produced (or different ones)
3. The Claude Code BeforeTool hook approach makes sense

Cost: ~$0.30 in Claude Code's own LLM calls (each session does 5-15 turns).
Modal: not used; runs locally.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STARTER = REPO_ROOT / "bench" / "scenarios" / "stripe_lite_v2" / "starter"
ORACLE_PATH = REPO_ROOT / "bench" / "oracle" / "scorer.py"
MARKERS_PATH = REPO_ROOT / "bench" / "scenarios" / "stripe_lite_v2" / "markers.json"
CLAUDE_CMD = r"C:\Users\aadit\AppData\Roaming\npm\claude.cmd"

# The same task each session gets.
TASK_PROMPT = """You are working on the stripe_lite repo. The codebase is a small FastAPI
subscriptions billing service in `app/` with `tests/` for pytest.

Add subscription cancellation with a 7-day grace period:

1. Schema in app/models.py: add columns
     canceled_at = Column(DateTime, nullable=True)
     cancel_reason = Column(String, nullable=True)
     grace_until = Column(DateTime, nullable=True)
   Use AMERICAN spelling (canceled_at, NOT cancelled_at).

2. New endpoints in app/routes/subscriptions.py:
     POST /subscriptions/{id}/cancel  — body {reason: str}; sets canceled_at=now, grace_until=now+7d.
                                        Returns 409 if already canceled.
     GET  /subscriptions/{id}/status  — returns {"state": "active"|"grace"|"canceled"}

3. New endpoint in a new file app/routes/admin.py:
     POST /admin/subscriptions/{id}/restore — admin-only; clears canceled_at, cancel_reason, grace_until.

4. Update app/routes/invoices.py generate_monthly_invoices:
     - Skip subscriptions where grace_until is in the past
     - When inside the grace window, mark the invoice as `prorated`

5. Add tests/test_cancel.py with tests for each new endpoint.

Make all the code work end-to-end. Run `pytest tests/ -x` to verify.
When complete, finish your turn — do not ask follow-up questions."""


def _make_workdir(tag: str) -> Path:
    """Copy starter to a fresh tempdir and `pip install` deps."""
    work = Path(tempfile.mkdtemp(prefix=f"option_b_{tag}_"))
    shutil.copytree(STARTER, work, dirs_exist_ok=True)
    print(f"  [{tag}] workdir = {work}")
    return work


def _capture_writes_via_fs(workdir: Path, agent_id: str, log_path: Path):
    """Watch workdir for file modifications, log them with agent attribution.

    NOTE: this is post-hoc — it sees the file change after Claude Code wrote
    it. Attribution is by which session is currently active. For this test
    we use TWO concurrent watchers, each tagged with its agent_id, and
    de-dupe overlapping writes by the existing audit pipeline.
    """
    sys.path.insert(0, str(REPO_ROOT / "sdk-python"))
    from synapse.watchers.fs_watcher import FSWatcher

    log_path.parent.mkdir(parents=True, exist_ok=True)

    def _emit(path, content_hash, ag_id, sess_id, ts_ms):
        rel = str(Path(path).relative_to(workdir)).replace("\\", "/")
        if rel.startswith(".synapse/"):
            return
        event = {
            "trace_id": sess_id,
            "span_id": f"{sess_id}:{ts_ms}",
            "agent_id": ag_id,
            "session_id": sess_id,
            "tool_name": "edit_file",
            "tool_args": {"path": rel},
            "ts_start_ms": ts_ms,
            "ts_end_ms": ts_ms,
            "raw": {"content_hash": content_hash, "source": "fs_watcher"},
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    w = FSWatcher(workdir, agent_id, "option_b_session", poll_interval_s=0.2)
    w.emit_callback = _emit
    w.start()
    return w


def _run_claude_session(
    workdir: Path,
    agent_id: str,
    prompt: str,
    log_capture_path: Path,
    timeout: int = 900,
) -> dict:
    """Run one claude -p session in workdir. Capture stdout for analysis."""
    env = os.environ.copy()
    env["SYNAPSE_AGENT_ID"] = agent_id
    env["SYNAPSE_SESSION_ID"] = "option_b_session"
    # Use a clean key (strip the 10-char prefix quirk on this machine)
    raw_key = env.get("ANTHROPIC_API_KEY", "")
    if len(raw_key) > 108 and not raw_key.startswith("sk-ant-"):
        env["ANTHROPIC_API_KEY"] = raw_key[10:]

    print(f"  [{agent_id}] starting claude session in {workdir}")
    started = time.time()
    # On Windows, claude.cmd needs cmd.exe to interpret it. Use shell=True.
    cmd_str = (
        f'"{CLAUDE_CMD}" -p {json.dumps(prompt)} '
        f'--allowedTools "Edit,Write,MultiEdit,Read,Bash(pytest:*),Bash(python:*),Bash(ls:*),Bash(cat:*)" '
        f'--dangerously-skip-permissions'
    )
    try:
        proc = subprocess.run(
            cmd_str, shell=True,
            cwd=str(workdir),
            env=env,
            capture_output=True, text=True,
            timeout=timeout,
        )
        elapsed = time.time() - started
        out = proc.stdout
        # Save full transcript
        log_capture_path.parent.mkdir(parents=True, exist_ok=True)
        log_capture_path.write_text(out, encoding="utf-8", errors="replace")
        print(f"  [{agent_id}] exit={proc.returncode} elapsed={elapsed:.1f}s stdout_len={len(out)}")
        return {
            "agent_id": agent_id,
            "exit_code": proc.returncode,
            "elapsed_s": elapsed,
            "stdout_path": str(log_capture_path),
            "stderr_tail": proc.stderr[-2000:] if proc.stderr else "",
        }
    except subprocess.TimeoutExpired as e:
        elapsed = time.time() - started
        print(f"  [{agent_id}] TIMEOUT after {elapsed:.1f}s")
        return {
            "agent_id": agent_id,
            "exit_code": -1,
            "elapsed_s": elapsed,
            "error": "timeout",
        }


def main():
    print("=== Option B: Real Claude Code two-session test ===")

    # ONE shared workdir — both Claude Code sessions write to the same FS.
    # That's the realistic scenario (two devs in the same repo).
    work = _make_workdir("shared")
    fs_log = work / ".synapse" / "runs" / "option_b_session.jsonl"

    # Start FS watchers — one per agent — BEFORE the sessions
    sys.path.insert(0, str(REPO_ROOT / "sdk-python"))
    w_alice = _capture_writes_via_fs(work, "alice-claude-code", fs_log)
    w_bob = _capture_writes_via_fs(work, "bob-claude-code", fs_log)

    time.sleep(0.5)  # let watchers settle baseline

    # Run both sessions in parallel via threads
    results = {}

    def _alice():
        results["alice"] = _run_claude_session(
            work, "alice-claude-code", TASK_PROMPT,
            REPO_ROOT / "bench" / "results" / "option_b" / "alice_transcript.json",
        )

    def _bob():
        results["bob"] = _run_claude_session(
            work, "bob-claude-code", TASK_PROMPT,
            REPO_ROOT / "bench" / "results" / "option_b" / "bob_transcript.json",
        )

    print("Spawning two Claude Code sessions in parallel...")
    t_alice = threading.Thread(target=_alice, daemon=True)
    t_bob = threading.Thread(target=_bob, daemon=True)
    t_alice.start()
    t_bob.start()
    t_alice.join()
    t_bob.join()

    # Stop watchers
    time.sleep(1.0)  # let last writes flush
    w_alice.stop()
    w_bob.stop()

    print(f"\nFS watcher emitted {w_alice.writes_emitted} (alice) + {w_bob.writes_emitted} (bob) write events")

    # Audit the FS log (only if we captured events)
    print("\nRunning synapse audit on the FS-watcher log...")
    audit_rep = None
    if fs_log.exists() and fs_log.stat().st_size > 0:
        from synapse.audit.pipeline import audit_traces
        audit_rep = audit_traces(str(fs_log))
        print(f"  events: {audit_rep.total_events}")
        print(f"  writes: {audit_rep.total_write_events}")
        print(f"  conflicts: {len(audit_rep.conflicts)}")
    else:
        print(f"  no FS-watcher events captured (sessions may have failed)")
        print(f"  fs_log path: {fs_log}")

    # Coherence on the final state
    print("\nScoring coherence against markers...")
    sys.path.insert(0, str(REPO_ROOT))
    from bench.oracle.scorer import score_coherence
    coh, breakdown = score_coherence(str(work), str(MARKERS_PATH))
    print(f"  coherence: {coh:.2f}")
    for r in breakdown:
        glyph = "[+]" if r.matched else "[-]"
        print(f"    {glyph} {r.id}")

    # Aggregate result
    summary = {
        "scenario": "Option B: real Claude Code two-session on Stripe Lite v2",
        "workdir": str(work),
        "agents": ["alice-claude-code", "bob-claude-code"],
        "alice_session": results.get("alice", {}),
        "bob_session": results.get("bob", {}),
        "fs_watcher_log": str(fs_log),
        "alice_writes_emitted": w_alice.writes_emitted,
        "bob_writes_emitted": w_bob.writes_emitted,
        "audit_findings": {
            "events": audit_rep.total_events if audit_rep else 0,
            "writes": audit_rep.total_write_events if audit_rep else 0,
            "conflicts": len(audit_rep.conflicts) if audit_rep else 0,
            "conflict_paths": (list({
                tuple(sorted([c.intention.tool_args.get("path", "?")] +
                              [x.tool_args.get("path", "?") for x in c.conflicting]))[0]
                for c in audit_rep.conflicts
            }) if audit_rep else []),
        } if audit_rep else {"events": 0, "writes": 0, "conflicts": 0,
                              "note": "no fs_log events captured"},
        "coherence": coh,
        "coherence_breakdown": [
            {"id": r.id, "category": r.category, "matched": r.matched}
            for r in breakdown
        ],
    }

    out_path = REPO_ROOT / "bench" / "results" / "option_b" / "option_b_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {out_path}")
    print(f"Workdir kept at {work} for inspection")


if __name__ == "__main__":
    main()
