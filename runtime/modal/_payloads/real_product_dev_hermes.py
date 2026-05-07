"""Real product-dev test through the Hermes Synapse integration.

This file is uploaded to a Modal sandbox and executed there. It:

1. Sets up real Redis + real Postgres + applies Synapse migrations
2. Installs the Synapse Hermes integration hooks
3. Spawns 3 concurrent agents that each call Anthropic Haiku and "write"
   to the SAME shared file (worst-case multi-agent collision)
4. Each write is wrapped with wrap_tool_call_for_synapse so INTENTION
   emission + the L2 router's CONFLICT detection are exercised live
5. Compares two modes: no_synapse vs with_synapse
6. Measures: alignment score, conflicts detected, envelopes on bus,
   intentions persisted, real LLM token usage
"""
import asyncio
import json
import os
import sys
import time
import uuid

# Make the synapse SDK importable. /opt is on path so `runtime.router.worker`
# imports cleanly (we mount synapse repo's runtime/ at /opt/runtime).
sys.path.insert(0, "/opt/synapse-sdk")
sys.path.insert(0, "/opt")

REDIS_URL = "redis://localhost:6379/0"
PG_DSN = "postgresql://synapse:synapse_dev@localhost:5432/synapse"

# Embed the migrations SQL directly so we don't depend on file paths
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


async def hermes_agent_step(agent_id, session_id, role_prompt, write_path, ant):
    """Simulate one Hermes-style agent: real LLM call + Synapse-coordinated write."""
    from synapse.integrations.hermes_integration import wrap_tool_call_for_synapse

    msg = await ant.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": role_prompt}],
    )
    content = msg.content[0].text if msg.content else ""

    async def actual_write():
        # In real Hermes this is the file-write tool. For our test we
        # actually write so we can inspect the artifact.
        with open(write_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"wrote {len(content)} bytes to {write_path}"

    result = await wrap_tool_call_for_synapse(
        "write_file", {"path": write_path}, actual_write,
        agent_id=agent_id,                    # explicit per-agent attribution
    )
    return {
        "agent_id": agent_id,
        "content": content,                      # full content for divergence detection
        "content_excerpt": content[:120],         # short excerpt for logs
        "write_result": result,
        "tokens_in": msg.usage.input_tokens,
        "tokens_out": msg.usage.output_tokens,
    }


async def run_scenario(with_synapse: bool):
    label = "with_synapse" if with_synapse else "no_synapse"
    print(f"\n--- mode: {label} ---")

    from anthropic import AsyncAnthropic
    from synapse.bus import Bus
    from synapse.state import StateGraph
    from synapse.integrations.hermes_integration import (
        install_hermes_synapse_hooks, register_synapse_agent, _hermes_runtime,
    )

    bus = Bus(REDIS_URL)
    state = StateGraph(PG_DSN)
    await bus.connect()
    await state.connect()
    session_id = f"prod_dev_{label}_{uuid.uuid4().hex[:8]}"

    router = None
    router_task = None
    if with_synapse:
        # Register one Synapse agent PER product-dev agent so the L2 router
        # treats them as distinct callers (its conflict query has agent_id != $2).
        await install_hermes_synapse_hooks(
            bus=bus, state=state, session_id=session_id,
            agent_id="architect", gate_ms=400,
        )
        await register_synapse_agent("backend")
        await register_synapse_agent("tester")
        from runtime.router.worker import Router

        router = Router(bus, state, session_id, consumer="prod_dev_router")
        router_task = asyncio.create_task(router.run())
        await asyncio.sleep(0.4)
    else:
        _hermes_runtime.clear()

    SHARED_PATH = f"/tmp/Todo_model_{label}.py"

    architect_prompt = (
        "You are the architect. Design a Todo data model in Python (SQLAlchemy). "
        "Use field name 'description' for the body text. Output ONLY the Python "
        "class, no prose, no markdown fences. 4 fields: id, description, completed, "
        "created_at."
    )
    backend_prompt = (
        "You are the backend engineer. Write a Todo data model in Python "
        "(SQLAlchemy). Use field name 'task' for the body text. Output ONLY the "
        "Python class, no prose, no markdown fences. 4 fields: id, task, completed, "
        "created_at."
    )
    tester_prompt = (
        "You are QA. Write a Todo data model in Python (SQLAlchemy). Use field "
        "name 'content' for the body text. Output ONLY the Python class, no prose. "
        "4 fields: id, content, completed, created_at."
    )

    ant = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    started = time.time()
    results = await asyncio.gather(
        hermes_agent_step("architect", session_id, architect_prompt, SHARED_PATH, ant),
        hermes_agent_step("backend", session_id, backend_prompt, SHARED_PATH, ant),
        hermes_agent_step("tester", session_id, tester_prompt, SHARED_PATH, ant),
        return_exceptions=True,
    )
    elapsed = time.time() - started

    # let coordinator/router catch up
    await asyncio.sleep(0.5)

    if router_task is not None:
        router.stop()
        try:
            await asyncio.wait_for(router_task, timeout=2)
        except asyncio.TimeoutError:
            router_task.cancel()

    # Inspect the bus + state graph
    if with_synapse:
        intent_rows = await state.pool.fetch(
            "SELECT id, agent_id, scope, status FROM intentions WHERE session_id = $1 ORDER BY created_at",
            session_id,
        )
        agent_rows = await state.pool.fetch(
            "SELECT id, status FROM agents WHERE session_id = $1", session_id,
        )
        redis = bus.redis
        stream_entries = await redis.xrange(
            f"synapse:session:{session_id}:events", count=100,
        )
        # Per-agent inboxes (where CONFLICTs land)
        inbox_entries = []
        for r in agent_rows:
            entries = await redis.xrange(
                f"synapse:agent:{r['id']}:inbox", count=20,
            )
            inbox_entries.extend(entries)
        conflict_count = 0
        for _eid, fields in inbox_entries:
            try:
                env = json.loads(fields["e"])
                if env["type"] == "CONFLICT":
                    conflict_count += 1
            except Exception:
                pass
    else:
        intent_rows = []
        agent_rows = []
        stream_entries = []
        inbox_entries = []
        conflict_count = 0

    # Read final file
    try:
        with open(SHARED_PATH, encoding="utf-8") as f:
            final_content = f.read()
    except FileNotFoundError:
        final_content = "(no file)"

    # Detect which Todo body-field name each agent actually used in the
    # FULL generated content (not just first 120 chars). Use word-boundary
    # match so 'description' isn't matched in 'descriptive', etc.
    import re
    FIELD_PATTERNS = {
        "description": re.compile(r"\bdescription\b\s*=\s*Column"),
        "task":        re.compile(r"\btask\b\s*=\s*Column"),
        "content":     re.compile(r"\bcontent\b\s*=\s*Column"),
    }
    per_agent_fields: list[str] = []
    field_names_used: set[str] = set()
    for r in results:
        if isinstance(r, dict):
            text = r.get("content", "") or ""
            agent_fields = [name for name, pat in FIELD_PATTERNS.items()
                            if pat.search(text)]
            per_agent_fields.append(",".join(agent_fields) or "?")
            for f in agent_fields:
                field_names_used.add(f)

    tokens_in = sum(r.get("tokens_in", 0) for r in results if isinstance(r, dict))
    tokens_out = sum(r.get("tokens_out", 0) for r in results if isinstance(r, dict))
    success_count = sum(1 for r in results if isinstance(r, dict))

    print(f"  elapsed:                 {elapsed:.1f}s")
    print(f"  agents that produced:    {success_count}/3")
    print(f"  per-agent field names:   {per_agent_fields}")
    print(f"  distinct field names:    {sorted(field_names_used)}")
    print(f"  total tokens in/out:     {tokens_in}/{tokens_out}")
    print(f"  envelopes on stream:     {len(stream_entries)}")
    print(f"  CONFLICT envelopes:      {conflict_count}")
    print(f"  intentions persisted:    {len(intent_rows)}")
    print(f"  agents persisted:        {len(agent_rows)}")
    print(f"  final file (first 240): {final_content[:240]!r}")

    await bus.close()
    await state.close()
    return {
        "mode": label,
        "session_id": session_id,
        "elapsed_seconds": round(elapsed, 2),
        "distinct_field_names": sorted(field_names_used),
        "alignment": 1.0 if len(field_names_used) == 1 else (1.0 / max(1, len(field_names_used))),
        "envelopes_on_stream": len(stream_entries),
        "conflicts_detected": conflict_count,
        "intentions_persisted": len(intent_rows),
        "agents_persisted": len(agent_rows),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "agent_results": [r if isinstance(r, dict) else {"error": str(r)} for r in results],
    }


async def main():
    print("=== REAL Hermes product-dev test ===")
    await apply_migrations()
    no_syn = await run_scenario(with_synapse=False)
    with_syn = await run_scenario(with_synapse=True)
    print("\n--- summary ---")
    print(
        f"  no_synapse:   distinct={no_syn['distinct_field_names']} "
        f"alignment={no_syn['alignment']:.2f} conflicts={no_syn['conflicts_detected']}"
    )
    print(
        f"  with_synapse: distinct={with_syn['distinct_field_names']} "
        f"alignment={with_syn['alignment']:.2f} conflicts={with_syn['conflicts_detected']} "
        f"intentions={with_syn['intentions_persisted']} envelopes={with_syn['envelopes_on_stream']}"
    )
    return {"no_synapse": no_syn, "with_synapse": with_syn}


if __name__ == "__main__":
    result = asyncio.run(main())
    print("\n--- result.json ---")
    print(json.dumps(result, indent=2))
