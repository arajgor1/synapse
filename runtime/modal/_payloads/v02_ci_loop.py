"""Real CI/CD loop test — Option A from the trust-but-verify ask.

Two LangGraph crews on a real git repo (Stripe Lite v2 starter), each turn
runs `git commit && pytest` and feeds the output back into the next turn's
prompt. Compares ci_only mode (no Synapse) vs ci_plus_synapse mode.

This is the cell I previously MODELED rather than ran. Now real.

The hypothesis to test is H5 from the campaign:
  "C9 (CI + Synapse) catches strictly more than C3 alone."

Equivalently: when both crews run with pytest gates, does Synapse still
add value, or is CI sufficient?
"""
from __future__ import annotations

import os
os.environ["LANGCHAIN_CALLBACKS_BACKGROUND"] = "false"

import asyncio
import json
import shutil
import subprocess
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "/opt/synapse-sdk")
sys.path.insert(0, "/opt")

REDIS_URL = "redis://localhost:6379/0"
PG_DSN = "postgresql://synapse:synapse_dev@localhost:5432/synapse"

# Stripe Lite v2 starter is copied into the sandbox at /opt/stripe_lite_v2_starter
STARTER_PATH = "/opt/stripe_lite_v2_starter"

# Shared migrations from the multi-orch payload
MIGRATIONS_SQL = (
    "CREATE TABLE IF NOT EXISTS agents ("
    " id text PRIMARY KEY, session_id text NOT NULL, tenant_id text,"
    " status text NOT NULL CHECK (status IN ('active','idle','crashed')),"
    " capabilities jsonb NOT NULL,"
    " subscribes text[] NOT NULL DEFAULT '{}',"
    " scopes_owned text[] NOT NULL DEFAULT '{}',"
    " last_heartbeat timestamptz NOT NULL DEFAULT now(),"
    " created_at timestamptz NOT NULL DEFAULT now()"
    ");"
    " CREATE TABLE IF NOT EXISTS intentions ("
    " id text PRIMARY KEY, agent_id text NOT NULL REFERENCES agents(id),"
    " session_id text NOT NULL, tenant_id text, scope text[] NOT NULL,"
    " action jsonb NOT NULL, expected_outcome text NOT NULL,"
    " blocking boolean NOT NULL DEFAULT false,"
    " status text NOT NULL CHECK (status IN ('pending','active','resolved','pivoted')),"
    " created_at timestamptz NOT NULL DEFAULT now(), resolved_at timestamptz"
    ");"
    " CREATE INDEX IF NOT EXISTS intentions_scope_gin ON intentions USING GIN (scope);"
    " CREATE TABLE IF NOT EXISTS beliefs ("
    " agent_id text NOT NULL, session_id text NOT NULL, tenant_id text,"
    " key text NOT NULL, value jsonb NOT NULL,"
    " confidence real NOT NULL CHECK (confidence BETWEEN 0 AND 1),"
    " source text NOT NULL CHECK (source IN ('observed','inferred','assumed')),"
    " evidence text, updated_at timestamptz NOT NULL DEFAULT now(),"
    " PRIMARY KEY (agent_id, key)"
    ");"
)


# Stripe Lite v2 task — the same task each crew gets.
TEAM_TASK = """\
You are the lead of an AI engineering crew working on a small subscription
billing service `stripe_lite` (FastAPI + SQLAlchemy + pytest).

Add subscription cancellation with a 7-day grace period:
  1. Schema: add columns canceled_at, cancel_reason, grace_until to subscriptions
  2. POST /subscriptions/{{id}}/cancel — sets canceled_at=now, grace_until=now+7d
  3. POST /admin/subscriptions/{{id}}/restore — admin-only; clears the cancel fields
  4. GET  /subscriptions/{{id}}/status — returns active|grace|canceled
  5. Invoice generation: skip past-grace, mark prorated within grace
  6. Tests for each endpoint

You have 1 worker agent: {worker_id}.

Each turn: assign ONE file for {worker_id} to write or modify. After the
worker writes, the test suite runs (`pytest tests/ -x`) and you receive the
result. If pytest is RED, your next turn must address the failure.

Output ONLY valid JSON:
  {{"thought": "<one-line plan>",
    "assignment": {{"agent": "{worker_id}", "file": "<path>", "spec": "<1-2 lines>"}},
    "done": false}}

When done: {{"thought":"...","assignment":null,"done":true}}.
"""


async def apply_migrations():
    import asyncpg
    conn = await asyncpg.connect(PG_DSN)
    try:
        await conn.execute(MIGRATIONS_SQL)
    finally:
        await conn.close()


def _seed_repo(repo_root: str):
    """Copy the Stripe Lite v2 starter into the working repo and git init."""
    if Path(repo_root).exists():
        shutil.rmtree(repo_root)
    shutil.copytree(STARTER_PATH, repo_root)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.email", "ci@bench"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.name", "ci-bench"], cwd=repo_root, check=True)
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "starter"], cwd=repo_root, check=True)


def _run_pytest(repo_root: str, timeout: int = 30) -> dict:
    """Run pytest, return structured outcome."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-x", "--tb=short", "-q"],
            cwd=repo_root, capture_output=True, text=True, timeout=timeout,
        )
        ok = proc.returncode == 0
        # Last 30 lines of output for next-turn prompt
        out_lines = (proc.stdout + proc.stderr).strip().split("\n")
        tail = "\n".join(out_lines[-30:])
        return {"ok": ok, "returncode": proc.returncode, "tail": tail[:2000]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": -1, "tail": "<pytest timeout>"}
    except Exception as e:
        return {"ok": False, "returncode": -2, "tail": f"<pytest error: {e}>"}


def _git_commit(repo_root: str, message: str) -> bool:
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
    proc = subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo_root,
                          capture_output=True, text=True)
    return proc.returncode == 0


async def run_worker_call(
    *, team_name: str, assignment: dict, mode: str, ant,
    repo_root: str, session_id: str,
):
    """One file write — wraps in synapse.intend() in synapse modes."""
    agent_id = assignment.get("agent", "?")
    file_rel = assignment.get("file", f"unknown_{int(time.time()*1000)}.py")
    spec = assignment.get("spec", "")
    write_path = f"{repo_root}/{file_rel}"

    # Generate file content (full file body — agents in this loop write
    # files, not patches, to keep the test simple)
    msg = await ant.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=900,
        messages=[{"role": "user",
                   "content": (
                       f"You are {agent_id} working on the stripe_lite repo. "
                       f"Write the FULL contents of {file_rel}.\n\n"
                       f"Spec: {spec}\n\n"
                       f"Output ONLY the file contents, no markdown fences, "
                       f"no commentary. Keep it under 80 lines. Make it valid "
                       f"Python that pytest can import."
                   )}],
    )
    content = msg.content[0].text if msg.content else ""
    if content.strip().startswith("```"):
        lines = content.strip().split("\n")
        content = "\n".join(lines[1:-1]) if len(lines) >= 2 else content

    proposed = {"path": file_rel, "content": content, "tool": "write_file"}
    scope = [f"repo.fs.{file_rel}:w"]

    if mode == "ci_only":
        os.makedirs(os.path.dirname(write_path) or ".", exist_ok=True)
        with open(write_path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"outcome": "success", "wrote_bytes": len(content),
                "saw_conflicts": False, "merged": False, "divergences": []}

    # synapse mode
    import synapse
    async with synapse.intend(
        scope=scope, agent=agent_id, session=session_id,
        expected_outcome=f"{agent_id}@{team_name}: {file_rel}",
        blocking=True, gate_ms=400,
        proposed_action=proposed,
    ) as i:
        if i.has_conflicts:
            print(f"  [SYNAPSE] {team_name}/{agent_id} CONFLICT on {file_rel} ({len(i.conflicts)} priors)", flush=True)
        final_content = content
        merged = False
        if i.merged_action and "content" in i.merged_action:
            final_content = i.merged_action["content"]
            merged = True
            print(f"  [SYNAPSE] {team_name}/{agent_id} auto_merged {file_rel}", flush=True)
        os.makedirs(os.path.dirname(write_path) or ".", exist_ok=True)
        with open(write_path, "w", encoding="utf-8") as f:
            f.write(final_content)
        i.set_state_diff({"content_preview": final_content[:1500],
                          "wrote_bytes": len(final_content)})
        for d in (i.divergences or []):
            print(f"  [SYNAPSE] BELIEF DIVERGENCE on {d.get('key','?')}: "
                  f"{d.get('distinct_values',[])[:2]}", flush=True)
    return {"outcome": "success", "wrote_bytes": len(final_content),
            "saw_conflicts": i.has_conflicts, "merged": merged,
            "divergences": list(i.divergences or [])}


async def run_team(
    *, team_name: str, worker_id: str, mode: str, ant,
    repo_root: str, session_id: str, capture: dict, max_turns: int = 6,
):
    """One team's autonomous loop, with pytest in the loop."""
    history: list[dict] = []
    last_pytest: dict | None = None
    print(f"  [{team_name}] starting (worker={worker_id})", flush=True)

    for turn in range(1, max_turns + 1):
        prompt = TEAM_TASK.format(worker_id=worker_id)
        prompt += f"\n\n## Turn {turn} of {max_turns}\n\n## History (this team only):\n"
        if not history:
            prompt += "(nothing yet)\n"
        else:
            for h in history[-5:]:
                prompt += f"- t{h['turn']}: {h['agent']} wrote {h['file']}\n"

        if last_pytest is not None:
            status = "PASSED" if last_pytest["ok"] else "FAILED"
            prompt += f"\n## Last pytest run: {status}\n"
            prompt += f"```\n{last_pytest['tail']}\n```\n"
            if not last_pytest["ok"]:
                prompt += "\nYour next assignment should address the test failure.\n"

        try:
            msg = await ant.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            print(f"  [{team_name}] orch LLM error t{turn}: {e}", flush=True)
            break

        plan_raw = (msg.content[0].text if msg.content else "{}").strip()
        if plan_raw.startswith("```"):
            plan_raw = plan_raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            if plan_raw.startswith("json"):
                plan_raw = plan_raw[4:].strip()
        try:
            plan = json.loads(plan_raw)
        except json.JSONDecodeError:
            print(f"  [{team_name}] t{turn} bad JSON, stopping. Raw: {plan_raw[:120]}", flush=True)
            break

        thought = plan.get("thought", "")
        assignment = plan.get("assignment")
        print(f"  [{team_name}] t{turn} thought: {thought[:80]}", flush=True)

        if plan.get("done") or not assignment:
            print(f"  [{team_name}] declared done at t{turn}", flush=True)
            break

        try:
            r = await run_worker_call(
                team_name=team_name, assignment=assignment, mode=mode, ant=ant,
                repo_root=repo_root, session_id=session_id,
            )
        except Exception as e:
            print(f"  [{team_name}] worker {assignment.get('agent')} crashed: {e}", flush=True)
            continue

        history.append({"turn": turn, **assignment, "outcome": r.get("outcome", "?")})
        capture["history"].append({"team": team_name, "turn": turn,
                                    **assignment, **r})

        # === CI step: commit + pytest ===
        committed = _git_commit(repo_root, f"{team_name}/{assignment.get('agent')} t{turn}: {assignment.get('file')}")
        py = _run_pytest(repo_root)
        last_pytest = py
        print(f"  [{team_name}] CI t{turn}: pytest {'PASSED' if py['ok'] else 'FAILED'} (rc={py['returncode']})", flush=True)
        capture["ci_history"].append({"team": team_name, "turn": turn,
                                       "committed": committed, "pytest_ok": py["ok"],
                                       "pytest_tail": py["tail"][:500]})


async def run_one_mode(mode: str, ant) -> dict:
    print(f"\n=== mode: {mode} ===", flush=True)
    session_id = f"v02_ci_{mode}_{uuid.uuid4().hex[:6]}"
    repo_root = f"/tmp/ci_{mode}_{uuid.uuid4().hex[:4]}"
    _seed_repo(repo_root)
    capture = {"history": [], "ci_history": []}

    bus = state = router_task = None
    if mode != "ci_only":
        import synapse
        synapse.set_llm(synapse.from_anthropic(ant, model="claude-haiku-4-5-20251001"))
        synapse.install(
            bus_url=REDIS_URL, state_dsn=PG_DSN, session_id=session_id,
            merge_policy=synapse.MergePolicy.auto_merge,
            emit_beliefs_from_tool_results=True,
        )
        from synapse.bus import Bus
        from synapse.state import StateGraph
        from runtime.router.worker import Router
        bus = Bus(REDIS_URL); state = StateGraph(PG_DSN)
        await bus.connect(); await state.connect()
        router = Router(bus, state, session_id, consumer=f"v02_ci_router_{mode}")
        router_task = asyncio.create_task(router.run())
        await asyncio.sleep(0.4)
    else:
        try:
            from synapse.intend import _runtime
            _runtime.clear()
        except Exception:
            pass

    started = time.time()

    # TWO TEAMS RUN IN PARALLEL — each with its own worker
    await asyncio.gather(
        run_team(team_name="alpha", worker_id="alpha_eng", mode=mode, ant=ant,
                 repo_root=repo_root, session_id=session_id,
                 capture=capture, max_turns=6),
        run_team(team_name="bravo", worker_id="bravo_eng", mode=mode, ant=ant,
                 repo_root=repo_root, session_id=session_id,
                 capture=capture, max_turns=6),
    )

    elapsed = time.time() - started

    # Final CI check
    final_pytest = _run_pytest(repo_root, timeout=60)

    # Final coherence scoring against the markers
    coherence_score, marker_results = _score_coherence_local(repo_root)

    # Cross-team file overlap analysis
    files_by_writer: dict[str, set[str]] = defaultdict(set)
    for h in capture["history"]:
        files_by_writer[h.get("team", "?")].add(h.get("file", ""))
    teams = list(files_by_writer.keys())
    cross_overlap = []
    if len(teams) >= 2:
        a, b = teams[0], teams[1]
        for f in files_by_writer[a] & files_by_writer[b]:
            cross_overlap.append(f)

    if router_task is not None:
        await asyncio.sleep(0.6)
        router.stop()
        try:
            await asyncio.wait_for(router_task, timeout=2)
        except asyncio.TimeoutError:
            router_task.cancel()
        if bus: await bus.close()
        if state: await state.close()

    # Tally synapse-emitted findings if present
    synapse_findings = {"conflict_envelopes": 0, "auto_merges": 0, "divergences": 0}
    for h in capture["history"]:
        if h.get("saw_conflicts"):
            synapse_findings["conflict_envelopes"] += 1
        if h.get("merged"):
            synapse_findings["auto_merges"] += 1
        synapse_findings["divergences"] += len(h.get("divergences") or [])

    summary = {
        "mode": mode,
        "session_id": session_id,
        "repo_root": repo_root,
        "elapsed_s": round(elapsed, 1),
        "files_written": len(set(h.get("file", "") for h in capture["history"])),
        "cross_team_file_overlap": cross_overlap,
        "n_cross_team_overlaps": len(cross_overlap),
        "ci_total_runs": len(capture["ci_history"]),
        "ci_red_runs": sum(1 for x in capture["ci_history"] if not x["pytest_ok"]),
        "ci_green_runs": sum(1 for x in capture["ci_history"] if x["pytest_ok"]),
        "final_pytest_ok": final_pytest["ok"],
        "final_pytest_tail": final_pytest["tail"][:1000],
        "coherence": coherence_score,
        "coherence_breakdown": marker_results,
        "synapse_findings": synapse_findings,
    }

    print(f"\n  === {mode} summary ===", flush=True)
    print(f"  elapsed:        {summary['elapsed_s']}s", flush=True)
    print(f"  files written:  {summary['files_written']}", flush=True)
    print(f"  cross-team:     {summary['n_cross_team_overlaps']} overlapping files", flush=True)
    print(f"  CI total/red:   {summary['ci_total_runs']}/{summary['ci_red_runs']}", flush=True)
    print(f"  final pytest:   {'GREEN' if summary['final_pytest_ok'] else 'RED'}", flush=True)
    print(f"  coherence:      {summary['coherence']:.2f}", flush=True)
    print(f"  synapse:        {summary['synapse_findings']}", flush=True)

    return {"summary": summary, "history": capture["history"], "ci_history": capture["ci_history"]}


def _score_coherence_local(repo_root: str) -> tuple[float, list]:
    """Self-contained coherence scorer (so we don't need to import bench/oracle in the sandbox)."""
    import re
    markers = [
        ("col_canceled_at", "schema", "**/models.py", r"canceled_at\s*=\s*Column\s*\(\s*DateTime", True),
        ("col_cancel_reason", "schema", "**/models.py", r"cancel_reason\s*=\s*Column\s*\(\s*String", True),
        ("col_grace_until", "schema", "**/models.py", r"grace_until\s*=\s*Column\s*\(\s*DateTime", True),
        ("no_cancelled_with_two_l", "schema", "**/models.py", r"cancelled_at", False),
        ("endpoint_cancel", "endpoint", "**/routes/**/*.py", r"/subscriptions/\{[^}]+\}/cancel", True),
        ("endpoint_restore", "endpoint", "**/routes/**/*.py", r"/admin/subscriptions/\{[^}]+\}/restore", True),
        ("endpoint_status", "endpoint", "**/routes/**/*.py", r"/subscriptions/\{[^}]+\}/status", True),
        ("state_value_active", "state", "**/routes/**/*.py", r"[\"']active[\"']", True),
        ("state_value_grace", "state", "**/routes/**/*.py", r"[\"']grace[\"']", True),
        ("state_value_canceled", "state", "**/routes/**/*.py", r"[\"']canceled[\"']", True),
        ("already_canceled_409", "error", "**/routes/**/*.py", r"status_code\s*=\s*409", True),
        ("grace_seven_days", "logic", "**/routes/**/*.py", r"(timedelta\s*\(\s*days\s*=\s*7|days=7)", True),
        ("invoice_grace_check", "logic", "**/routes/invoices.py", r"grace_until", True),
        ("invoice_prorated_flag", "logic", "**/routes/invoices.py", r"prorated", True),
        ("test_for_cancel", "tests", "**/tests/**/*.py", r"def\s+test_.*cancel", True),
    ]
    results = []
    matched = 0
    for mid, cat, glob, pattern, expected in markers:
        regex = re.compile(pattern, re.MULTILINE)
        hit = False
        for path in Path(repo_root).glob(glob):
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if regex.search(content):
                hit = True
                break
        actual = hit if expected else not hit
        if actual:
            matched += 1
        results.append({"id": mid, "category": cat, "matched": actual})
    return (matched / len(markers) if markers else 0.0), results


async def main():
    print("=== v0.2.1 CI/CD-loop comparison test ===", flush=True)
    print(f"  REDIS={REDIS_URL}", flush=True)
    print(f"  PG={PG_DSN}", flush=True)

    await apply_migrations()

    from anthropic import AsyncAnthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key.startswith("sk-ant-api03-") and len(api_key) > 108:
        # Strip prefix junk if present
        idx = api_key.find("sk-ant-api03-")
        api_key = api_key[idx:]
    ant = AsyncAnthropic(api_key=api_key)

    out = {"modes": {}}
    for mode in ("ci_only", "ci_plus_synapse"):
        try:
            res = await run_one_mode(mode, ant)
            out["modes"][mode] = res
        except Exception as e:
            print(f"  [{mode}] failed: {e}", flush=True)
            import traceback
            traceback.print_exc()
            out["modes"][mode] = {"error": str(e)}

    # Final comparison
    print("\n=== FINAL COMPARISON ===", flush=True)
    fmt = "  {:<22} {:>10} {:>10} {:>12} {:>14} {:>10}"
    print(fmt.format("mode", "files", "overlaps", "ci_red", "final_pytest", "coherence"), flush=True)
    for mode in ("ci_only", "ci_plus_synapse"):
        s = out["modes"].get(mode, {}).get("summary", {})
        if not s:
            continue
        print(fmt.format(
            mode, s.get("files_written", 0), s.get("n_cross_team_overlaps", 0),
            s.get("ci_red_runs", 0),
            "GREEN" if s.get("final_pytest_ok") else "RED",
            f"{s.get('coherence', 0):.2f}",
        ), flush=True)

    # Write to /tmp so the entrypoint can fish it out
    out_path = f"/tmp/v02_ci_loop_{int(time.time())}.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nWrote {out_path}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
