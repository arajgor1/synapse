"""Week 3a live test: real CrewAI 3-agent crew + real Anthropic Haiku +
synapse.install(framework="crewai").

CrewAI's standard pattern: define Agents + Tasks, hand them to a Crew,
call ``crew.kickoff()``. Tasks have ``expected_output`` strings that
mention file paths; we plant 3 tasks all targeting the same file path
so synapse.crewai's scope inference catches the collision.

Validates Week 3a's core ergonomic: any framework, same 3-line install
pattern, real conflict detection.
"""
import os
os.environ["LANGCHAIN_CALLBACKS_BACKGROUND"] = "false"

import asyncio
import json
import sys
import time
import uuid

sys.path.insert(0, "/opt/synapse-sdk")
sys.path.insert(0, "/opt")

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


async def apply_migrations():
    import asyncpg
    conn = await asyncpg.connect(PG_DSN)
    try:
        await conn.execute(MIGRATIONS_SQL)
    finally:
        await conn.close()


async def run(with_synapse: bool):
    label = "with_synapse" if with_synapse else "no_synapse"
    print(f"\n=== mode: {label} ===")

    session_id = f"v02_crewai_{label}_{uuid.uuid4().hex[:6]}"

    router_task = None
    bus = None
    state = None

    if with_synapse:
        # The 3-line install
        import synapse
        synapse.set_llm(synapse.from_anthropic(model="claude-haiku-4-5-20251001"))
        result = synapse.install(
            framework="crewai",
            bus_url=REDIS_URL,
            state_dsn=PG_DSN,
            session_id=session_id,
        )
        print(f"  synapse.install -> {result}")

        # Start the L2 router
        from synapse.bus import Bus
        from synapse.state import StateGraph
        from runtime.router.worker import Router

        bus = Bus(REDIS_URL)
        state = StateGraph(PG_DSN)
        await bus.connect()
        await state.connect()
        router = Router(bus, state, session_id, consumer="v02_crewai_router")
        router_task = asyncio.create_task(router.run())
        await asyncio.sleep(0.4)
    else:
        # Make sure no leftover synapse runtime
        try:
            from synapse.intend import _runtime
            _runtime.clear()
        except Exception:
            pass

    # Build the CrewAI workload — 3 agents, 3 tasks, all targeting auth.py
    from crewai import Agent, Task, Crew, LLM
    crewai_llm = LLM(model="anthropic/claude-haiku-4-5-20251001",
                     api_key=os.environ["ANTHROPIC_API_KEY"])

    agent_a = Agent(role="security_engineer",
                    goal="Audit and update auth.py for CVE fixes",
                    backstory="Expert at security patches.",
                    llm=crewai_llm, verbose=False, allow_delegation=False)
    agent_b = Agent(role="api_engineer",
                    goal="Add rate limiting to auth.py",
                    backstory="API performance specialist.",
                    llm=crewai_llm, verbose=False, allow_delegation=False)
    agent_c = Agent(role="logging_engineer",
                    goal="Add audit logging to auth.py",
                    backstory="Compliance expert.",
                    llm=crewai_llm, verbose=False, allow_delegation=False)

    task_a = Task(
        description="Output a 4-line Python snippet patching CVE-2026-1 in auth.py "
                    "(add input validation). Output ONLY the snippet.",
        expected_output="A patched src/auth.py snippet (4 lines).",
        agent=agent_a,
    )
    task_b = Task(
        description="Output a 4-line Python decorator that adds rate limiting "
                    "to functions in src/auth.py. Output ONLY the snippet.",
        expected_output="A rate-limit decorator for src/auth.py.",
        agent=agent_b,
    )
    task_c = Task(
        description="Output a 4-line Python logging statement to add at the "
                    "start of src/auth.py functions. Output ONLY the snippet.",
        expected_output="An audit-log line for src/auth.py.",
        agent=agent_c,
    )

    crew = Crew(agents=[agent_a, agent_b, agent_c],
                tasks=[task_a, task_b, task_c],
                verbose=False)

    started = time.time()
    try:
        # crew.kickoff is sync; run on a thread so we don't block the loop
        result = await asyncio.to_thread(crew.kickoff)
    except Exception as e:
        print(f"  crew.kickoff raised: {e}")
        result = None
    elapsed = time.time() - started

    await asyncio.sleep(0.6)

    if router_task is not None:
        router.stop()
        try:
            await asyncio.wait_for(router_task, timeout=2)
        except asyncio.TimeoutError:
            router_task.cancel()

    intent_rows, agent_rows, stream_count, conflict_count = [], [], 0, 0
    if with_synapse and state is not None and bus is not None:
        intent_rows = await state.pool.fetch(
            "SELECT id, agent_id, scope, status FROM intentions WHERE session_id=$1 ORDER BY created_at",
            session_id,
        )
        agent_rows = await state.pool.fetch(
            "SELECT id FROM agents WHERE session_id=$1", session_id,
        )
        redis = bus.redis
        stream_entries = await redis.xrange(f"synapse:session:{session_id}:events", count=200)
        stream_count = len(stream_entries)
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

    print(f"  elapsed:                 {elapsed:.1f}s")
    print(f"  envelopes on stream:     {stream_count}")
    print(f"  intentions persisted:    {len(intent_rows)}")
    print(f"  agents persisted:        {len(agent_rows)}")
    print(f"  CONFLICT envelopes:      {conflict_count}")

    return {
        "mode": label,
        "session_id": session_id,
        "elapsed_seconds": round(elapsed, 2),
        "envelopes_on_stream": stream_count,
        "intentions_persisted": len(intent_rows),
        "agents_persisted": len(agent_rows),
        "conflicts_detected": conflict_count,
    }


async def main():
    print("=== v0.2 Week 3a live test: CrewAI + synapse.install(framework='crewai') ===")
    await apply_migrations()
    no_syn = await run(with_synapse=False)
    with_syn = await run(with_synapse=True)

    print("\n--- summary ---")
    print(f"  no_synapse:    conflicts={no_syn['conflicts_detected']}  envelopes={no_syn['envelopes_on_stream']}")
    print(f"  with_synapse:  conflicts={with_syn['conflicts_detected']}  envelopes={with_syn['envelopes_on_stream']}  intentions={with_syn['intentions_persisted']}  agents={with_syn['agents_persisted']}")

    return {"no_synapse": no_syn, "with_synapse": with_syn}


if __name__ == "__main__":
    result = asyncio.run(main())
    print("\n--- result.json ---")
    print(json.dumps(result, indent=2))
