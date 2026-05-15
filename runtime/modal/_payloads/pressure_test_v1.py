"""Pressure-test v1 payload — run the autoapply pipeline once per Python
framework adapter (10 of them), capture per-framework artifacts.

OpenClaw (TS) is run separately by a Node payload.

Each framework run produces in /tmp/pressuretest/{framework}/:
  - resume_parsed.json, matched_roles.json, scrub_report.json,
    cover_letters/*.md, validated_application.json,
    submission_results.json, envelopes.jsonl, summary.json
  - stdout.log (the run's stdout)

After all 10 finish, we dump the entire artifact tree to stdout
(wrapped in markers) so the local Modal driver can extract everything
to disk without needing Modal volumes.
"""
from __future__ import annotations

import asyncio, json, os, subprocess, sys, time, traceback
from pathlib import Path

sys.path.insert(0, "/opt/synapse-sdk")
sys.path.insert(0, "/opt")
sys.path.insert(0, "/opt/pressure_test")  # where shared/ + orchestrators/ live

REDIS_URL = "redis://localhost:6379/0"
PG_DSN = "postgresql://synapse:synapse_dev@localhost:5432/synapse"

# Frameworks under test, ordered cheapest-first so failures fail fast.
FRAMEWORKS = [
    "autogen",
    "hermes",
    "openai_agents",
    "pydantic_ai",
    "smolagents",
    "agno",
    "langgraph",
    "llama_index",
    "crewai",
    "google_adk",
]


# ---------------------------------------------------------------------------
# Migrations — same as v32 bench
# ---------------------------------------------------------------------------
MIGRATIONS_SQL = (
    "CREATE TABLE IF NOT EXISTS agents ("
    " id text PRIMARY KEY, session_id text NOT NULL, tenant_id text,"
    " status text NOT NULL CHECK (status IN ('active','idle','crashed')),"
    " capabilities jsonb NOT NULL,"
    " subscribes text[] NOT NULL DEFAULT '{}',"
    " scopes_owned text[] NOT NULL DEFAULT '{}',"
    " last_heartbeat timestamptz NOT NULL DEFAULT now(),"
    " created_at timestamptz NOT NULL DEFAULT now());"
    " CREATE TABLE IF NOT EXISTS intentions ("
    " id text PRIMARY KEY, agent_id text NOT NULL REFERENCES agents(id),"
    " session_id text NOT NULL, tenant_id text, scope text[] NOT NULL,"
    " action jsonb NOT NULL, expected_outcome text NOT NULL,"
    " blocking boolean NOT NULL DEFAULT false,"
    " status text NOT NULL CHECK (status IN ('pending','active','resolved','pivoted')),"
    " created_at timestamptz NOT NULL DEFAULT now(), resolved_at timestamptz);"
)


async def apply_migrations() -> None:
    import asyncpg
    conn = await asyncpg.connect(PG_DSN)
    try: await conn.execute(MIGRATIONS_SQL)
    finally: await conn.close()


# ---------------------------------------------------------------------------
# Per-framework runner — imports the orchestrator module dynamically and
# isolates the run so one framework's crash can't kill the rest.
# ---------------------------------------------------------------------------
async def run_one(framework: str, root_out: Path) -> dict:
    out_dir = root_out / framework
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {"framework": framework, "ok": False, "elapsed_s": 0.0,
              "error": "", "intents": 0, "thoughts": 0, "conflicts": 0,
              "injections_detected": 0}
    t0 = time.time()
    try:
        # Dynamic import so a broken module doesn't kill the whole run
        mod_name = f"orchestrators.{framework}_orchestrator"
        mod = __import__(mod_name, fromlist=["run"])
        ctx = await asyncio.wait_for(
            mod.run(REDIS_URL, PG_DSN, out_dir),
            timeout=180,
        )
        s = ctx.summary
        summary.update({
            "ok": True,
            "elapsed_s": round(time.time() - t0, 1),
            "intents": s.intents_total,
            "intents_resolved": s.intents_resolved,
            "thoughts": s.thoughts_total,
            "conflicts": s.conflicts_total,
            "injections_detected": s.injections_detected,
            "fingerprints_laundered": s.fingerprints_laundered,
            "steps_count": len(s.steps),
            "session": ctx.session_id,
        })
    except Exception as e:
        summary["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        summary["elapsed_s"] = round(time.time() - t0, 1)
        (out_dir / "ERROR.txt").write_text(
            f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
            encoding="utf-8",
        )
    return summary


async def main() -> None:
    print("=== Synapse pressure test v1 — autoapply across 10 frameworks ===")
    print(f"  synapse: {__import__('synapse').__version__}")
    print(f"  frameworks: {FRAMEWORKS}")
    await apply_migrations()

    root_out = Path("/tmp/pressuretest")
    root_out.mkdir(parents=True, exist_ok=True)

    per_framework = []
    for fw in FRAMEWORKS:
        print(f"\n----- running: {fw} -----", flush=True)
        res = await run_one(fw, root_out)
        per_framework.append(res)
        status = "OK " if res["ok"] else "FAIL"
        print(f"  {status} {fw}  intents={res['intents']} thoughts={res['thoughts']} "
              f"conflicts={res['conflicts']} elapsed={res['elapsed_s']}s")
        if res.get("error"):
            print(f"  ERROR: {res['error']}")

    # Write a master summary
    master = {
        "frameworks_tested": len(FRAMEWORKS),
        "ok_count": sum(1 for r in per_framework if r["ok"]),
        "per_framework": per_framework,
    }
    (root_out / "master_summary.json").write_text(
        json.dumps(master, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 90)
    print("  PRESSURE-TEST MASTER SUMMARY")
    print("=" * 90)
    print(f"  {master['ok_count']} / {master['frameworks_tested']} frameworks PASSed")
    for r in per_framework:
        status = "OK  " if r["ok"] else "FAIL"
        print(f"    {status} {r['framework']:14s} "
              f"intents={r['intents']:3d} thoughts={r['thoughts']:3d} "
              f"conflicts={r['conflicts']:3d} elapsed={r['elapsed_s']:6.1f}s "
              f"{('err: ' + r['error']) if r.get('error') else ''}")

    # Dump everything in /tmp/pressuretest/ to stdout, file-by-file, so
    # the local driver can extract.
    print("\n" + "=" * 90)
    print("  ARTIFACT DUMP (full /tmp/pressuretest/ tree)")
    print("=" * 90)
    for path in sorted(root_out.rglob("*")):
        if not path.is_file(): continue
        rel = path.relative_to(root_out)
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            # Binary or unreadable — skip
            continue
        print(f"\n>>>>>>>>>> FILE: {rel}  ({len(content)} bytes) <<<<<<<<<<")
        print(content)
        print(f"<<<<<<<<<< END {rel} <<<<<<<<<<")
    print("\n" + "=" * 90)
    print("  END ARTIFACT DUMP")
    print("=" * 90)


if __name__ == "__main__":
    asyncio.run(main())
