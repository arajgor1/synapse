"""Week 4 live test: Instagram-clone backend with MergePolicy.auto_merge.

The headline demo for v0.2:

  no_synapse:        models/user.py is silently overwritten 3 times.
                     Final file has only the last writer's fields.

  with_synapse +     models/user.py is auto-merged via the user's BYO-LLM.
  auto_merge:        Final file has fields from ALL THREE engineers.

3 specialist agents (db / api / auth) all generate User-model code via
real Anthropic Haiku, then write to models/user.py. With auto_merge
configured, each subsequent agent's CONFLICT triggers an LLM-mediated
merge that incorporates the prior writer's fields before writing.
"""
import os
os.environ["LANGCHAIN_CALLBACKS_BACKGROUND"] = "false"

import asyncio
import json
import logging
import sys
import time
import uuid

sys.path.insert(0, "/opt/synapse-sdk")
sys.path.insert(0, "/opt")

# Surface auto_merge debug logs
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logging.getLogger("synapse.policies.builtin").setLevel(logging.INFO)

REDIS_URL = "redis://localhost:6379/0"
PG_DSN = "postgresql://synapse:synapse_dev@localhost:5432/synapse"

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
)

PROMPTS = {
    "db_engineer": (
        "Write a SQLAlchemy User model class. Fields: id (PK), username "
        "(unique str), email (unique str), created_at (DateTime). Include "
        "the imports + Base. Output ONLY the Python code, no markdown fences."
    ),
    "api_engineer": (
        "Write a SQLAlchemy User model class with profile fields. Fields: "
        "id, username, email, bio (str, nullable), avatar_url (str, "
        "nullable), created_at. Include imports + Base. Output ONLY the "
        "Python code, no markdown."
    ),
    "auth_engineer": (
        "Write a SQLAlchemy User model class with auth fields. Fields: "
        "id, username, email, password_hash (str), last_login (DateTime, "
        "nullable), created_at. Include imports + Base. Output ONLY the "
        "Python code, no markdown."
    ),
}


async def apply_migrations():
    import asyncpg
    conn = await asyncpg.connect(PG_DSN)
    try:
        await conn.execute(MIGRATIONS_SQL)
    finally:
        await conn.close()


async def agent_step(agent_id, session_id, prompt, write_path, ant, mode: str):
    """One agent: real LLM call, then write through synapse.intend with the
    appropriate policy."""
    import synapse

    msg = await ant.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    content = msg.content[0].text if msg.content else ""

    if mode == "no_synapse":
        os.makedirs(os.path.dirname(write_path) or ".", exist_ok=True)
        with open(write_path, "w", encoding="utf-8") as f:
            f.write(content)
        return {
            "agent_id": agent_id,
            "merged": False,
            "tokens_in": msg.usage.input_tokens,
            "tokens_out": msg.usage.output_tokens,
            "wrote_bytes": len(content),
        }

    # Synapse path: with_synapse OR with_synapse_automerge
    policy = (
        synapse.MergePolicy.auto_merge
        if mode == "with_synapse_automerge"
        else synapse.MergePolicy.redirect
    )
    proposed = {"path": write_path, "content": content}

    async with synapse.intend(
        scope=[f"repo.fs.models/user.py:w"],
        agent=agent_id,
        session=session_id,
        expected_outcome=f"{agent_id} writes models/user.py",
        blocking=True,
        gate_ms=400,
        merge_policy=policy,
        proposed_action=proposed,
    ) as i:
        # If auto_merge ran successfully, use the merged content
        final_content = content
        merged_flag = False
        if i.merged_action and "content" in i.merged_action:
            final_content = i.merged_action["content"]
            merged_flag = True

        os.makedirs(os.path.dirname(write_path) or ".", exist_ok=True)
        with open(write_path, "w", encoding="utf-8") as f:
            f.write(final_content)
        i.set_state_diff({
            "content": final_content[:2000],   # surface for next agent's auto_merge
            "wrote_bytes": len(final_content),
        })

    return {
        "agent_id": agent_id,
        "merged": merged_flag,
        "tokens_in": msg.usage.input_tokens,
        "tokens_out": msg.usage.output_tokens,
        "wrote_bytes": len(final_content),
        "saw_conflicts": i.has_conflicts,
        "policy_rationale": i.policy_rationale,
    }


async def run(mode: str):
    label = mode
    print(f"\n=== mode: {label} ===")
    session_id = f"v02_w4_{label}_{uuid.uuid4().hex[:6]}"

    repo_root = f"/tmp/insta_w4_{label}_{uuid.uuid4().hex[:4]}"
    write_path = f"{repo_root}/models/user.py"

    from anthropic import AsyncAnthropic
    ant = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    router_task = None
    bus = None
    state = None

    if mode != "no_synapse":
        import synapse
        synapse.set_llm(synapse.from_anthropic(ant, model="claude-haiku-4-5-20251001"))
        synapse.install(
            bus_url=REDIS_URL,
            state_dsn=PG_DSN,
            session_id=session_id,
            merge_policy=(
                synapse.MergePolicy.auto_merge if mode == "with_synapse_automerge"
                else synapse.MergePolicy.redirect
            ),
        )

        from synapse.bus import Bus
        from synapse.state import StateGraph
        from runtime.router.worker import Router

        bus = Bus(REDIS_URL)
        state = StateGraph(PG_DSN)
        await bus.connect()
        await state.connect()
        router = Router(bus, state, session_id, consumer="v02_w4_router")
        router_task = asyncio.create_task(router.run())
        await asyncio.sleep(0.4)
    else:
        try:
            from synapse.intend import _runtime
            _runtime.clear()
        except Exception:
            pass

    started = time.time()
    # Sequential — each agent's write should see the prior writes' resolutions
    results = []
    for agent_id, prompt in PROMPTS.items():
        try:
            r = await agent_step(agent_id, session_id, prompt, write_path, ant, mode)
        except Exception as e:
            r = {"agent_id": agent_id, "error": str(e)}
        results.append(r)
        # small gap so the gate window can drain
        await asyncio.sleep(0.3)
    elapsed = time.time() - started

    await asyncio.sleep(0.6)
    if router_task is not None:
        router.stop()
        try:
            await asyncio.wait_for(router_task, timeout=2)
        except asyncio.TimeoutError:
            router_task.cancel()

    # Read the final file
    try:
        with open(write_path, encoding="utf-8") as f:
            final = f.read()
    except FileNotFoundError:
        final = ""

    # Look for marker fields each engineer SHOULD have contributed.
    # If auto_merge did its job, all 3 markers should appear in the same file.
    markers = {
        "db_engineer (created_at)": "created_at" in final,
        "api_engineer (bio + avatar_url)": "bio" in final and "avatar_url" in final,
        "auth_engineer (password_hash + last_login)": "password_hash" in final and "last_login" in final,
    }
    survived = sum(1 for v in markers.values() if v)

    intent_rows, agent_rows, stream_count, conflict_count = [], [], 0, 0
    if mode != "no_synapse" and state is not None and bus is not None:
        intent_rows = await state.pool.fetch(
            "SELECT id, agent_id, scope, status FROM intentions WHERE session_id=$1 ORDER BY created_at",
            session_id,
        )
        agent_rows = await state.pool.fetch(
            "SELECT id FROM agents WHERE session_id=$1", session_id,
        )
        redis = bus.redis
        stream_count = len(await redis.xrange(f"synapse:session:{session_id}:events", count=200))
        for r in agent_rows:
            entries = await redis.xrange(f"synapse:agent:{r['id']}:inbox", count=20)
            for _eid, fields in entries:
                try:
                    env = json.loads(fields["e"])
                    if env["type"] == "CONFLICT":
                        conflict_count += 1
                except Exception:
                    pass

    if bus is not None:
        await bus.close()
    if state is not None:
        await state.close()

    tokens_in = sum(r.get("tokens_in", 0) for r in results)
    tokens_out = sum(r.get("tokens_out", 0) for r in results)
    merges = sum(1 for r in results if r.get("merged"))

    print(f"  elapsed:                   {elapsed:.1f}s")
    print(f"  agents that ran:           {len(results)}/3")
    print(f"  auto-merges performed:     {merges}")
    print(f"  tokens in/out:             {tokens_in}/{tokens_out}")
    print(f"  envelopes on stream:       {stream_count}")
    print(f"  intentions persisted:      {len(intent_rows)}")
    print(f"  agents persisted:          {len(agent_rows)}")
    print(f"  CONFLICT envelopes:        {conflict_count}")
    print(f"  marker fields surviving in final file: {survived}/3")
    for marker, ok in markers.items():
        print(f"    {'✓' if ok else '✗'} {marker}")
    print(f"  final models/user.py first 80 chars: {final[:80]!r}")

    return {
        "mode": label,
        "session_id": session_id,
        "elapsed_seconds": round(elapsed, 2),
        "agents_ran": len(results),
        "auto_merges": merges,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "envelopes_on_stream": stream_count,
        "intentions_persisted": len(intent_rows),
        "agents_persisted": len(agent_rows),
        "conflicts_detected": conflict_count,
        "markers_surviving": survived,
        "marker_breakdown": markers,
        "final_first_line": (final.splitlines() or [""])[0][:120],
        "final_full": final,
        "agent_results": results,
    }


async def main():
    print("=== v0.2 Week 4 live test: MergePolicy.auto_merge on Instagram-clone ===")
    await apply_migrations()
    no_syn = await run("no_synapse")
    with_syn = await run("with_synapse")
    with_auto = await run("with_synapse_automerge")

    print("\n--- summary ---")
    print(f"  no_synapse:             markers_surviving={no_syn['markers_surviving']}/3  conflicts={no_syn['conflicts_detected']}")
    print(f"  with_synapse (redirect): markers_surviving={with_syn['markers_surviving']}/3  conflicts={with_syn['conflicts_detected']}  merges={with_syn['auto_merges']}")
    print(f"  with_synapse_automerge:  markers_surviving={with_auto['markers_surviving']}/3  conflicts={with_auto['conflicts_detected']}  merges={with_auto['auto_merges']}")

    return {"no_synapse": no_syn, "with_synapse_redirect": with_syn, "with_synapse_automerge": with_auto}


if __name__ == "__main__":
    result = asyncio.run(main())
    print("\n--- result.json ---")
    # Trim final_full from agent_results for the printed JSON to avoid massive output
    trimmed = {}
    for k, v in result.items():
        c = dict(v)
        if "final_full" in c:
            c["final_full"] = c["final_full"][:1500] + ("..." if len(c["final_full"]) > 1500 else "")
        trimmed[k] = c
    print(json.dumps(trimmed, indent=2, default=str))
