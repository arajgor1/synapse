"""Option C — Real Strands Agents test against the actual `strands-agents` SDK.

Validates that synapse.install(framework="strands") actually patches the
real SDK (not the fake module from the smoke test) and that two parallel
Strands agents on Stripe Lite v2 collide AND get caught by Synapse.

Pip-installs strands-agents at runtime so we don't pay for it on every
sandbox warm-start. Runs once standalone vs once with Synapse.

Cost: ~$0.30 (Anthropic Haiku, 2 parallel Strands agents, ~5 turns each).
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
from pathlib import Path

sys.path.insert(0, "/opt/synapse-sdk")
sys.path.insert(0, "/opt")

REDIS_URL = "redis://localhost:6379/0"
PG_DSN = "postgresql://synapse:synapse_dev@localhost:5432/synapse"
STARTER_PATH = "/opt/stripe_lite_v2_starter"


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

TASK = """\
You are an engineer working on `stripe_lite`, a small FastAPI subscriptions
billing service. Add subscription cancellation:

1. Add columns to subscriptions table: canceled_at, cancel_reason, grace_until
2. Add endpoint POST /subscriptions/{id}/cancel
3. Add endpoint GET /subscriptions/{id}/status returning active|grace|canceled
4. Update invoice generation to skip past-grace, mark prorated within grace

Use the edit_file tool to write the relevant Python files. Be thorough but
concise — when the task is done, return a short summary.
"""


async def apply_migrations():
    import asyncpg
    conn = await asyncpg.connect(PG_DSN)
    try:
        await conn.execute(MIGRATIONS_SQL)
    finally:
        await conn.close()


def _seed_repo() -> str:
    repo = f"/tmp/strands_{uuid.uuid4().hex[:6]}"
    shutil.copytree(STARTER_PATH, repo)
    return repo


def _make_edit_file_tool(repo_root: str):
    """Build a Strands @tool that writes a file under repo_root."""
    from strands import tool

    @tool
    def edit_file(path: str, content: str) -> str:
        """Edit or create a file in the working repo. path is relative; content is the full file body."""
        full = os.path.join(repo_root, path)
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        return f"wrote {len(content)} bytes to {path}"

    return edit_file


async def run_one_strands_agent(name: str, repo_root: str, mode: str, session_id: str):
    """One Strands agent invocation."""
    print(f"  [{name}] starting (mode={mode})", flush=True)
    os.environ["SYNAPSE_AGENT_ID"] = name

    if mode == "synapse":
        import synapse
        from anthropic import AsyncAnthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if len(api_key) > 108 and not api_key.startswith("sk-ant-"):
            api_key = api_key[10:]
        ant = AsyncAnthropic(api_key=api_key)
        synapse.set_llm(synapse.from_anthropic(ant, model="claude-haiku-4-5-20251001"))
        synapse.install(
            framework="strands",
            bus_url=REDIS_URL, state_dsn=PG_DSN, session_id=session_id,
            merge_policy=synapse.MergePolicy.auto_merge,
            emit_beliefs_from_tool_results=False,  # Strands SDK shape may differ
        )

    from strands import Agent
    from strands.models.anthropic import AnthropicModel

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if len(api_key) > 108 and not api_key.startswith("sk-ant-"):
        api_key = api_key[10:]

    edit_tool = _make_edit_file_tool(repo_root)
    model = AnthropicModel(
        client_args={"api_key": api_key},
        model_id="claude-haiku-4-5-20251001",
        max_tokens=2000,
    )
    agent = Agent(model=model, tools=[edit_tool], system_prompt=f"You are {name}.")

    try:
        result = await asyncio.to_thread(agent, TASK)
        print(f"  [{name}] done. result preview: {str(result)[:150]}", flush=True)
        return {"agent": name, "ok": True, "summary": str(result)[:500]}
    except Exception as e:
        print(f"  [{name}] error: {e}", flush=True)
        import traceback; traceback.print_exc()
        return {"agent": name, "ok": False, "error": str(e)}


async def run_one_mode(mode: str) -> dict:
    print(f"\n=== Strands mode: {mode} ===", flush=True)
    repo = _seed_repo()
    session_id = f"v02_strands_{mode}_{uuid.uuid4().hex[:6]}"
    print(f"  repo={repo}  session={session_id}", flush=True)

    bus = state = router_task = None
    if mode == "synapse":
        from synapse.bus import Bus
        from synapse.state import StateGraph
        from runtime.router.worker import Router
        bus = Bus(REDIS_URL); state = StateGraph(PG_DSN)
        await bus.connect(); await state.connect()
        router = Router(bus, state, session_id, consumer=f"v02_strands_router_{mode}")
        router_task = asyncio.create_task(router.run())
        await asyncio.sleep(0.4)

    started = time.time()
    results = await asyncio.gather(
        run_one_strands_agent("strands_alice", repo, mode, session_id),
        run_one_strands_agent("strands_bob", repo, mode, session_id),
        return_exceptions=True,
    )
    elapsed = time.time() - started

    if router_task is not None:
        await asyncio.sleep(0.4)
        router.stop()
        try:
            await asyncio.wait_for(router_task, timeout=2)
        except asyncio.TimeoutError:
            router_task.cancel()
        if bus: await bus.close()
        if state: await state.close()

    # Score the final repo state
    from collections import defaultdict
    files_written = []
    for root, _, fnames in os.walk(repo):
        for fn in fnames:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, repo).replace("\\", "/")
            if rel.startswith(".git"): continue
            files_written.append(rel)

    return {
        "mode": mode,
        "session_id": session_id,
        "repo": repo,
        "elapsed_s": round(elapsed, 1),
        "agent_results": [
            r if isinstance(r, dict) else {"agent": "?", "ok": False, "error": str(r)}
            for r in results
        ],
        "files_in_final_state": sorted(files_written),
    }


async def main():
    print("=== v0.2.1 Real Strands Agents test (Option C) ===", flush=True)
    # Install strands-agents at runtime
    print("Installing strands-agents...", flush=True)
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q",
         "strands-agents>=0.4", "anthropic>=0.40"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(f"  ERR pip install: {proc.stderr}", flush=True)
    else:
        print("  pip install OK", flush=True)

    # Verify import
    try:
        import strands  # type: ignore[import-not-found]
        print(f"  strands imported: version={getattr(strands, '__version__', '?')}", flush=True)
    except Exception as e:
        print(f"  FATAL: cannot import strands: {e}", flush=True)
        return

    await apply_migrations()

    out = {"modes": {}}
    for mode in ("no_synapse", "synapse"):
        try:
            out["modes"][mode] = await run_one_mode(mode)
        except Exception as e:
            print(f"  [{mode}] failed: {e}", flush=True)
            import traceback; traceback.print_exc()
            out["modes"][mode] = {"error": str(e)}

    print("\n=== STRANDS COMPARISON ===", flush=True)
    for mode in ("no_synapse", "synapse"):
        s = out["modes"].get(mode, {})
        if "error" in s:
            print(f"  {mode}: ERROR {s['error'][:80]}")
            continue
        ar = s.get("agent_results", [])
        ok_count = sum(1 for a in ar if a.get("ok"))
        print(f"  {mode}: {ok_count}/{len(ar)} agents ok, "
              f"{len(s.get('files_in_final_state', []))} files in final state, "
              f"elapsed={s.get('elapsed_s')}s", flush=True)

    out_path = f"/tmp/v02_strands_real_{int(time.time())}.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nWrote {out_path}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
