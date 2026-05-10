"""v0.2.2a3 adapter E2E test (v4) — validates the ContextVar fix.

The v3 payload (``v022_adapter_e2e.py``) uses
``os.environ["SYNAPSE_AGENT_ID"] = name`` which races under
``asyncio.gather`` — that's the symptom that motivated Bug 1. The v3
Modal log shows ``langchain agents=['bob']`` — both writes attributed
to whichever coroutine wrote the env var last.

This v4 payload uses the new ``synapse.with_agent(name)`` ContextVar
API (shipped in v0.2.2a2 and surfaced via top-level ``synapse``
namespace). Under correct attribution, BOTH ``alice`` and ``bob``
should appear in the persisted intentions for langchain/langgraph/
smolagents/autogen — proving the fix landed.

We focus on the four frameworks that fully E2E'd in v3 (autogen,
langchain, langgraph, smolagents). The other 7 install-only-verified
adapters are the subject of the W2.1 sprint, not this validation run.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from typing import Any

sys.path.insert(0, "/opt/synapse-sdk")
sys.path.insert(0, "/opt")

REDIS_URL = "redis://localhost:6379/0"
PG_DSN = "postgresql://synapse:synapse_dev@localhost:5432/synapse"


# Same migrations as v3 (kept inline for sandbox isolation)
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


async def apply_migrations() -> None:
    import asyncpg
    conn = await asyncpg.connect(PG_DSN)
    try:
        await conn.execute(MIGRATIONS_SQL)
    finally:
        await conn.close()


# -------- Per-framework: invoke the REAL patched dispatch with ContextVar attribution --------

async def test_autogen(repo_root: str, session_id: str) -> dict:
    """Invoke FunctionTool.run TWICE, each in its own with_agent() block."""
    import synapse
    from autogen_core.tools import FunctionTool
    from autogen_core import CancellationToken

    def _edit(path: str, content: str) -> str:
        full = os.path.join(repo_root, path)
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        return f"wrote {len(content)} bytes"

    tool = FunctionTool(_edit, name="edit_file", description="Edit a file")
    os.environ["SYNAPSE_SESSION_ID"] = session_id

    async def call_as(agent_name: str, content: str):
        # ContextVar attribution — race-free under asyncio.gather (v0.2.2a2+).
        # Replaces the env-var pattern that produced the v3 'agents=[bob]' bug.
        with synapse.with_agent(agent_name):
            args_model = tool.args_type()
            args = args_model(path="app/models.py", content=content)
            try:
                return await tool.run(args, CancellationToken())
            except Exception as e:
                return f"err: {type(e).__name__}: {str(e)[:80]}"

    a, b = await asyncio.gather(
        call_as("alice", "alice writes\n"),
        call_as("bob", "bob writes\n"),
    )
    return {"alice": str(a)[:80], "bob": str(b)[:80]}


async def test_langchain(repo_root: str, session_id: str) -> dict:
    """LangChain BaseTool.ainvoke — patched method, ContextVar attribution."""
    import synapse
    from langchain_core.tools import StructuredTool

    def _edit(path: str, content: str) -> str:
        full = os.path.join(repo_root, path)
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        return f"wrote {len(content)} bytes"

    tool = StructuredTool.from_function(_edit, name="edit_file", description="Edit a file")
    os.environ["SYNAPSE_SESSION_ID"] = session_id

    async def call_as(agent_name: str, content: str):
        with synapse.with_agent(agent_name):
            try:
                return await tool.ainvoke({"path": "app/models.py", "content": content})
            except Exception as e:
                return f"err: {type(e).__name__}: {str(e)[:100]}"

    a, b = await asyncio.gather(
        call_as("alice", "alice langchain\n"),
        call_as("bob", "bob langchain\n"),
    )
    return {"alice": str(a)[:80], "bob": str(b)[:80]}


async def test_langgraph(repo_root: str, session_id: str) -> dict:
    """LangGraph uses LangChain tools — same surface as test_langchain."""
    return await test_langchain(repo_root, session_id)


async def test_smolagents(repo_root: str, session_id: str) -> dict:
    """smolagents Tool.__call__ — patched method, ContextVar attribution."""
    import synapse
    from smolagents import Tool

    class EditTool(Tool):
        name = "edit_file"
        description = "Edit a file"
        inputs = {"path": {"type": "string", "description": "Path"},
                  "content": {"type": "string", "description": "Content"}}
        output_type = "string"
        def forward(self, path: str, content: str) -> str:
            full = os.path.join(repo_root, path)
            os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
            with open(full, "w", encoding="utf-8") as f:
                f.write(content)
            return f"wrote {len(content)} bytes"

    tool = EditTool()
    os.environ["SYNAPSE_SESSION_ID"] = session_id

    async def call_as(agent_name: str, content: str):
        # The smolagents wrapper bridges via run_coro_blocking, so the
        # ContextVar must be set in the calling task (we are).
        with synapse.with_agent(agent_name):
            try:
                return await asyncio.to_thread(
                    tool, path="app/models.py", content=content,
                )
            except Exception as e:
                return f"err: {type(e).__name__}: {str(e)[:100]}"

    a, b = await asyncio.gather(
        call_as("alice", "alice smol\n"),
        call_as("bob", "bob smol\n"),
    )
    return {"alice": str(a)[:80], "bob": str(b)[:80]}


# -------- Driver --------

async def main() -> None:
    import synapse
    print(f"=== v0.2.2a3 adapter E2E v4 — ContextVar attribution validation ===")
    print(f"  synapse v{synapse.__version__}")

    await apply_migrations()

    # Install adapters once at module scope (matches real-user deployment).
    synapse.install(
        framework="autogen",
        bus_url=REDIS_URL, state_dsn=PG_DSN,
    )
    synapse.install(framework="langchain")
    synapse.install(framework="smolagents")

    # Ensure the live router is running so CONFLICTs route back to inboxes.
    # (Modal sandbox uses real Redis + Postgres, not zero-infra.)
    import subprocess
    router_session_id = f"v4_{int(time.time())}"
    router_proc = subprocess.Popen(
        [
            sys.executable, "-m", "runtime.router.worker",
            "--session", router_session_id,
            "--redis-url", REDIS_URL,
            "--postgres-dsn", PG_DSN,
        ],
        env={**os.environ, "PYTHONPATH": "/opt"},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    await asyncio.sleep(0.5)  # let router boot

    repo_root = "/tmp/v4_repo"
    os.makedirs(repo_root, exist_ok=True)

    results: dict[str, dict] = {}
    for name, fn in [
        ("autogen",   test_autogen),
        ("langchain", test_langchain),
        ("langgraph", test_langgraph),
        ("smolagents", test_smolagents),
    ]:
        # Each framework gets its own session so prior intentions don't bleed
        sess = f"{router_session_id}_{name}"
        # Re-spawn router for new session (cheap)
        # Actually keep one router and use one session per test so we can
        # query the DB per-section.
        sess = router_session_id  # single session, one router
        print(f"\n=== {name} ===")
        try:
            r = await fn(repo_root, sess)
        except Exception as e:
            r = {"err": f"{type(e).__name__}: {e}"}
        # Query Postgres for the agent_ids we just persisted
        import asyncpg
        conn = await asyncpg.connect(PG_DSN)
        try:
            rows = await conn.fetch(
                "SELECT DISTINCT agent_id FROM intentions WHERE session_id = $1 "
                "AND created_at >= now() - interval '60 seconds' "
                "AND id NOT IN (SELECT id FROM intentions WHERE agent_id = 'router')",
                sess,
            )
            agents = sorted({r_["agent_id"] for r_ in rows})
            n_intents = await conn.fetchval(
                "SELECT count(*) FROM intentions WHERE session_id = $1 "
                "AND created_at >= now() - interval '60 seconds'",
                sess,
            )
        finally:
            await conn.close()
        results[name] = {
            "result": r,
            "n_intents": int(n_intents or 0),
            "distinct_agents": agents,
            "fix_validated": (set(agents) >= {"alice", "bob"}),
        }
        print(f"  intents={results[name]['n_intents']} agents={agents} "
              f"fix_validated={results[name]['fix_validated']}")
        print(f"  result={r}")

    print("\n" + "=" * 70)
    print("  SUMMARY (v0.2.2a3 ContextVar fix validation)")
    print("=" * 70)
    print(f"  {'framework':<14} {'intents':>8} {'agents':<22} fix_validated")
    for name in ("autogen", "langchain", "langgraph", "smolagents"):
        r = results[name]
        print(f"  {name:<14} {r['n_intents']:>8}  "
              f"{','.join(r['distinct_agents']):<22} {r['fix_validated']}")

    out = f"/tmp/v022_adapter_e2e_v4_{int(time.time())}.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {out}")

    # Clean up router
    try:
        router_proc.terminate()
        router_proc.wait(timeout=2)
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(main())
