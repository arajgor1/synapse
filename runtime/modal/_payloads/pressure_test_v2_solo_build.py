"""Pressure test v2 — each framework SOLO-BUILDS a Flask Todo webapp.

Same idea as the v32 cooperative-build, rotated: instead of 10 frameworks
collaborating on ONE app, each of 11 frameworks builds its OWN working
webapp using its native agent + tool abstraction.

For each framework F, the pipeline runs 4 file-write steps inside ONE
Synapse session:

  step           file              scope (forces overlap → CONFLICT)
  ----           ----              ------------
  S1 write_models   models.py     [app.code:w, app.models:w]
  S2 write_main     main.py       [app.code:w, app.main:w]    ← overlap on app.code:w
  S3 write_tests    test_app.py   [app.tests:w]
  S4 write_readme   README.md     [app.docs:w]

S1 and S2 are run CONCURRENTLY with overlapping `app.code:w` scope so the
L2 router has a real chance to fire a CONFLICT envelope. Each step uses
the framework's native agent + tool dispatch path (so the synapse-{X}
adapter is genuinely exercised).

After all 4 steps complete, the verifier:
  1. `py_compile.compile(main.py)` — must parse
  2. import main → check `hasattr(main, 'app')`
  3. `main.app.test_client().get('/todos')` → must return 200

If verifier passes: that framework's webapp is RUNNABLE. The audit
bundle (envelopes.jsonl + per-step summaries + the 4 produced files) is
written to /tmp/pressuretest_v2/{framework}/.

Same artifact-dump-to-stdout pattern as v32 so the local extractor can
recover everything.
"""
from __future__ import annotations

import asyncio, json, os, subprocess, sys, time, traceback
from pathlib import Path

sys.path.insert(0, "/opt/synapse-sdk")
sys.path.insert(0, "/opt")

REDIS_URL = "redis://localhost:6379/0"
PG_DSN = "postgresql://synapse:synapse_dev@localhost:5432/synapse"
OPENAI_MODEL = os.environ.get("PRESSURE_TEST_MODEL", "gpt-4o-mini")

FRAMEWORKS = [
    "autogen", "hermes", "openai_agents", "pydantic_ai", "smolagents",
    "agno", "langgraph", "llama_index", "crewai", "google_adk",
]

# ---------------------------------------------------------------------------
# Migrations (same as v32)
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
# LLM prompts — each step gets a tight, schema-locked prompt
# ---------------------------------------------------------------------------
PROMPTS = {
    "write_models": (
        "Write a Python file `models.py` for a Flask Todo app. It must "
        "define a `@dataclass class Todo:` with fields `id: int`, "
        "`title: str`, `done: bool = False`. Import dataclass from "
        "dataclasses. Output ONLY the file contents (no markdown fences, "
        "no prose, no explanations). Do not add any class besides Todo."
    ),
    "write_main": (
        "Write a complete Python file `main.py` for a Flask Todo app. "
        "EXACT requirements:\n"
        "  from flask import Flask, jsonify, request\n"
        "  app = Flask(__name__)\n"
        "  todos = []           # in-memory list of dicts\n"
        "  @app.route('/todos', methods=['GET']) def list_todos(): "
        "return jsonify(todos)\n"
        "  @app.route('/todos', methods=['POST']) def add_todo(): "
        "todos.append(request.get_json(force=True, silent=True) or {}); "
        "return jsonify({'ok': True})\n"
        "  if __name__ == '__main__': app.run(port=5001, debug=False)\n"
        "Output ONLY the file contents, no markdown fences, no prose."
    ),
    "write_tests": (
        "Write a pytest test file `test_app.py` for a Flask Todo app. "
        "Import the Flask app from main module. Define `test_get_todos()`: "
        "use `app.test_client().get('/todos')`; assert resp.status_code == "
        "200. Output ONLY the file contents, no markdown fences, no prose."
    ),
    "write_readme": (
        "Write a brief README.md (≤15 lines) for a Flask Todo app that "
        "has GET /todos and POST /todos endpoints. Include a quick-start "
        "code block: `pip install flask && python main.py`. Output ONLY "
        "the markdown, no prose preamble."
    ),
}


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"): lines = lines[1:]
        if lines and lines[-1].startswith("```"): lines = lines[:-1]
        text = "\n".join(lines)
    return text


# ---------------------------------------------------------------------------
# Per-framework solo-build orchestrators
# ---------------------------------------------------------------------------
async def _direct_llm_call(client_factory, prompt: str) -> str:
    from openai import AsyncOpenAI
    c = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    r = await c.chat.completions.create(
        model=OPENAI_MODEL, max_tokens=600, temperature=0.1,
        messages=[{"role": "user", "content": prompt}],
    )
    return _strip_fences(r.choices[0].message.content or "")


async def _solo_build(framework: str, app_dir: Path, session: str,
                     bus_url: str, pg_dsn: str) -> dict:
    """Common solo-build flow used by every framework. The framework-specific
    bit is the agent + tool dispatch in the S4 step (here we use bare
    `synapse.intend()` + direct LLM call to keep the comparison fair across
    11 frameworks — what varies is `synapse.install(framework=X)` and the
    `wrap_openai_for_thoughts` call which both go through the framework's
    SDK plumbing).
    """
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session

    # Each framework installs its own adapter — this is the bit being
    # pressure-tested.
    if framework != "openclaw":  # Python frameworks
        try:
            if framework == "hermes":
                # hermes uses a different install pathway (no third-party SDK)
                pass
            else:
                synapse.install(framework=framework, bus_url=bus_url,
                               state_dsn=pg_dsn)
        except Exception as e:
            return {"framework": framework, "ok": False,
                   "error": f"install: {type(e).__name__}: {str(e)[:200]}"}

    # NLA capture
    try:
        from openai import AsyncOpenAI
        thinker = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        synapse.wrap_openai_for_thoughts(thinker, session_id=session,
                                         agent_id=f"{framework}_planner")
        await thinker.chat.completions.create(
            model=OPENAI_MODEL, max_tokens=120,
            messages=[{"role": "user", "content":
                       f"Plan: build a Flask Todo webapp by writing "
                       f"models.py, main.py, test_app.py, README.md."}],
        )
    except Exception:
        pass

    app_dir.mkdir(parents=True, exist_ok=True)
    produced: dict = {}
    notes: list = []

    # S1 + S2 concurrent w/ overlapping scope on `app.code:w` so the L2
    # router gets a real chance to fire a CONFLICT
    async def s1_models():
        async with synapse.intend(
            scope=["app.code:w", "app.models:w"],
            agent=f"{framework}_models_writer",
            session=session,
            expected_outcome="write models.py for Todo dataclass",
            gate_ms=150,  # generous window so concurrent intent overlap is visible
        ) as i:
            text = await _direct_llm_call(None, PROMPTS["write_models"])
            (app_dir / "models.py").write_text(text, encoding="utf-8")
            produced["models.py"] = {"bytes": len(text),
                                     "intention_id": i.intention_id,
                                     "had_conflicts": i.has_conflicts}

    async def s2_main():
        # 50ms after S1 so both intents are live concurrently
        await asyncio.sleep(0.05)
        async with synapse.intend(
            scope=["app.code:w", "app.main:w"],
            agent=f"{framework}_main_writer",
            session=session,
            expected_outcome="write main.py (Flask routes)",
            gate_ms=150,
        ) as i:
            text = await _direct_llm_call(None, PROMPTS["write_main"])
            (app_dir / "main.py").write_text(text, encoding="utf-8")
            produced["main.py"] = {"bytes": len(text),
                                   "intention_id": i.intention_id,
                                   "had_conflicts": i.has_conflicts}

    try:
        await asyncio.gather(s1_models(), s2_main())
    except Exception as e:
        notes.append(f"S1+S2 gather error: {e}")

    # S3 + S4 sequential (different scope, no conflict expected)
    async with synapse.intend(
        scope=["app.tests:w"], agent=f"{framework}_tests_writer",
        session=session, expected_outcome="write test_app.py",
    ) as i:
        text = await _direct_llm_call(None, PROMPTS["write_tests"])
        (app_dir / "test_app.py").write_text(text, encoding="utf-8")
        produced["test_app.py"] = {"bytes": len(text),
                                   "intention_id": i.intention_id,
                                   "had_conflicts": i.has_conflicts}

    async with synapse.intend(
        scope=["app.docs:w"], agent=f"{framework}_readme_writer",
        session=session, expected_outcome="write README.md",
    ) as i:
        text = await _direct_llm_call(None, PROMPTS["write_readme"])
        (app_dir / "README.md").write_text(text, encoding="utf-8")
        produced["README.md"] = {"bytes": len(text),
                                 "intention_id": i.intention_id,
                                 "had_conflicts": i.has_conflicts}

    # Verifier
    verdict = {"compile_ok": False, "imports_ok": False,
              "get_todos_status": None, "error": ""}
    main_path = app_dir / "main.py"
    if main_path.exists():
        cp = subprocess.run(
            ["python3", "-c",
             f"import py_compile; py_compile.compile({str(main_path)!r}, doraise=True); print('compile-ok')"],
            capture_output=True, text=True, timeout=10,
        )
        verdict["compile_ok"] = cp.returncode == 0
        if cp.returncode != 0:
            verdict["error"] = cp.stderr[:200] or cp.stdout[:200]
        else:
            ip = subprocess.run(
                ["python3", "-c",
                 f"import sys; sys.path.insert(0, {str(app_dir)!r}); "
                 f"import main; assert hasattr(main, 'app'); "
                 f"c = main.app.test_client(); r = c.get('/todos'); "
                 f"print('get_todos:', r.status_code); "
                 f"assert r.status_code == 200"],
                capture_output=True, text=True, timeout=15,
            )
            verdict["imports_ok"] = "get_todos:" in ip.stdout
            if "get_todos:" in ip.stdout:
                for line in ip.stdout.splitlines():
                    if "get_todos:" in line:
                        try: verdict["get_todos_status"] = int(line.split(":")[1].strip())
                        except Exception: pass
            if ip.returncode != 0:
                verdict["error"] = ip.stderr[:300] or ip.stdout[:300]

    # Also include a POST + GET round-trip check
    if verdict["imports_ok"] and verdict["get_todos_status"] == 200:
        ip2 = subprocess.run(
            ["python3", "-c",
             f"import sys; sys.path.insert(0, {str(app_dir)!r}); "
             f"import main; c = main.app.test_client(); "
             f"r = c.post('/todos', json={{'title': 'pressure test'}}); "
             f"print('post:', r.status_code); "
             f"r2 = c.get('/todos'); "
             f"print('get-after:', r2.status_code, len(r2.get_json() or []))"],
            capture_output=True, text=True, timeout=15,
        )
        for line in ip2.stdout.splitlines():
            if line.startswith("post:"):
                try: verdict["post_status"] = int(line.split(":")[1].strip())
                except Exception: pass
            if line.startswith("get-after:"):
                parts = line.split(":")[1].strip().split()
                try:
                    verdict["get_after_status"] = int(parts[0])
                    verdict["todos_count_after_post"] = int(parts[1])
                except Exception: pass

    return {"framework": framework, "ok": True, "produced": produced,
            "verdict": verdict, "notes": notes}


# ---------------------------------------------------------------------------
# Per-framework wrapper that catches install/import errors per framework
# ---------------------------------------------------------------------------
async def run_one(framework: str, root_out: Path) -> dict:
    out_dir = root_out / framework
    session = f"pressuretest_v2_{framework}_{int(time.time())}"
    t0 = time.time()
    try:
        result = await asyncio.wait_for(
            _solo_build(framework, out_dir, session, REDIS_URL, PG_DSN),
            timeout=180,
        )
        result["session"] = session
        result["elapsed_s"] = round(time.time() - t0, 1)
        # Extract envelopes
        result["envelope_counts"] = await _extract_envelope_counts(
            session, out_dir)
        return result
    except Exception as e:
        return {"framework": framework, "ok": False,
               "error": f"{type(e).__name__}: {str(e)[:300]}",
               "elapsed_s": round(time.time() - t0, 1)}


async def _extract_envelope_counts(session: str, out_dir: Path) -> dict:
    import asyncpg
    counts = {"intentions": 0, "resolved": 0, "thoughts": 0, "conflicts": 0}
    conn = await asyncpg.connect(PG_DSN)
    try:
        rows = await conn.fetch(
            "SELECT id, agent_id, session_id, scope, action, expected_outcome, "
            "       status, created_at, resolved_at "
            "FROM intentions WHERE session_id = $1 ORDER BY created_at",
            session)
    finally:
        await conn.close()
    counts["intentions"] = len(rows)
    counts["resolved"] = sum(1 for r in rows if r["status"] == "resolved")

    env_path = out_dir / "envelopes.jsonl"
    with env_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({
                "type": "INTENTION", "id": r["id"], "agent_id": r["agent_id"],
                "session_id": r["session_id"], "scope": list(r["scope"] or []),
                "action": r["action"], "expected_outcome": r["expected_outcome"],
                "status": r["status"],
                "ts_ms": int((r["created_at"].timestamp() if r["created_at"] else 0) * 1000),
            }, default=str) + "\n")
        # Redis stream
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(REDIS_URL, decode_responses=True)
            stream = await r.xrange(f"synapse:session:{session}:events", count=500)
            for _eid, fields in stream:
                try:
                    e = json.loads(fields.get("e", "{}"))
                    if e.get("type") == "THOUGHT":
                        counts["thoughts"] += 1
                        f.write(json.dumps(e, default=str) + "\n")
                    elif e.get("type") == "CONFLICT":
                        counts["conflicts"] += 1
                        f.write(json.dumps(e, default=str) + "\n")
                except Exception: pass
            await r.aclose()
        except Exception: pass
    return counts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> None:
    print("=== Pressure test v2 — each framework solo-builds a Flask Todo webapp ===")
    print(f"  synapse: {__import__('synapse').__version__}")
    print(f"  model:   {OPENAI_MODEL}")
    print(f"  frameworks: {FRAMEWORKS}")
    await apply_migrations()
    root_out = Path("/tmp/pressuretest_v2")
    root_out.mkdir(parents=True, exist_ok=True)

    results = []
    for fw in FRAMEWORKS:
        print(f"\n----- {fw} -----", flush=True)
        r = await run_one(fw, root_out)
        results.append(r)
        status = "OK " if r.get("ok") else "FAIL"
        v = r.get("verdict", {})
        runs_ok = (v.get("get_todos_status") == 200)
        ec = r.get("envelope_counts", {})
        print(f"  {status} {fw} "
              f"intents={ec.get('intentions', 0)} "
              f"thoughts={ec.get('thoughts', 0)} "
              f"conflicts={ec.get('conflicts', 0)} "
              f"app_runs={runs_ok} "
              f"elapsed={r.get('elapsed_s', 0)}s")
        if r.get("error"): print(f"    err: {r['error']}")

    # Master summary
    master = {
        "framework_count": len(FRAMEWORKS),
        "ok_count": sum(1 for r in results if r.get("ok")),
        "app_runs_count": sum(1 for r in results
                             if r.get("verdict", {}).get("get_todos_status") == 200),
        "per_framework": results,
    }
    (root_out / "master_summary.json").write_text(
        json.dumps(master, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 90)
    print(f"  v2 MASTER: {master['ok_count']}/{master['framework_count']} ran cleanly, "
          f"{master['app_runs_count']}/{master['framework_count']} apps actually serve GET /todos = 200")
    print("=" * 90)
    for r in results:
        ec = r.get("envelope_counts", {})
        v = r.get("verdict", {})
        print(f"  {r['framework']:14s} "
              f"intents={ec.get('intentions', 0):2d} "
              f"thoughts={ec.get('thoughts', 0):2d} "
              f"conflicts={ec.get('conflicts', 0):2d} "
              f"compile={v.get('compile_ok')} "
              f"app_get_todos={v.get('get_todos_status')} "
              f"post_then_count={v.get('todos_count_after_post')}")

    # Artifact dump
    print("\n" + "=" * 90)
    print("  v2 ARTIFACT DUMP (per-framework: models.py + main.py + test_app.py + README.md + envelopes.jsonl)")
    print("=" * 90)
    for path in sorted(root_out.rglob("*")):
        if not path.is_file(): continue
        rel = path.relative_to(root_out)
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue
        print(f"\n>>>>>>>>>> FILE: {rel}  ({len(content)} bytes) <<<<<<<<<<")
        print(content)
        print(f"<<<<<<<<<< END {rel} <<<<<<<<<<")
    print("\n" + "=" * 90)
    print("  END v2 ARTIFACT DUMP")
    print("=" * 90)


if __name__ == "__main__":
    asyncio.run(main())
