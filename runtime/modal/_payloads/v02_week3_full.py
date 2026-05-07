"""Week 3 full integration test: LangGraph + CrewAI on the same Synapse
stack, both visible in the dashboard.

The test simulates a realistic mixed-framework deployment:
  - One LangGraph crew working on auth code
  - One CrewAI crew working on the same auth code
  - Both wired to the same Synapse session
  - Verify both produce intentions in the state graph and conflicts
    cross-fire (a LangGraph agent's claim collides with a CrewAI agent's)

Validates Week 3's ultimate goal: Synapse as a framework-neutral
coordination layer that catches conflicts even when the agents come
from different ecosystems.
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
SHARED_PATH = "src/auth.py"

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


async def run_langgraph_crew(session_id: str, anthropic_client) -> dict:
    """LangGraph 2-agent crew, both writing to SHARED_PATH."""
    from langchain_core.tools import tool
    from langgraph.graph import StateGraph, END
    from typing import TypedDict

    @tool
    def write_file(path: str, content: str) -> str:
        """Write content to a file path under /tmp. Returns confirmation string."""
        full = f"/tmp/{path}"
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        return f"wrote {len(content)} bytes"

    class GS(TypedDict):
        outputs: dict

    async def lg_security(state: GS):
        msg = await anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=120,
            messages=[{"role": "user", "content":
                       "Write a 3-line Python validate_token() function for auth.py. Code only."}],
        )
        text = msg.content[0].text if msg.content else ""
        await write_file.ainvoke(
            {"path": SHARED_PATH, "content": text},
            config={"metadata": {"agent_name": "lg_security", "session_id": session_id}},
        )
        return {"outputs": {**state.get("outputs", {}), "lg_security": text[:80]}}

    async def lg_logging(state: GS):
        msg = await anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=120,
            messages=[{"role": "user", "content":
                       "Write a 3-line Python audit_log() function for auth.py. Code only."}],
        )
        text = msg.content[0].text if msg.content else ""
        await write_file.ainvoke(
            {"path": SHARED_PATH, "content": text},
            config={"metadata": {"agent_name": "lg_logging", "session_id": session_id}},
        )
        return {"outputs": {**state.get("outputs", {}), "lg_logging": text[:80]}}

    builder = StateGraph(GS)
    builder.add_node("lg_security", lg_security)
    builder.add_node("lg_logging", lg_logging)
    builder.set_entry_point("lg_security")
    builder.add_edge("lg_security", "lg_logging")
    builder.add_edge("lg_logging", END)
    graph = builder.compile()

    import synapse
    cb = synapse.frameworks.langgraph.get_callback()
    return await graph.ainvoke(
        {"outputs": {}},
        config={"callbacks": [cb], "metadata": {"session_id": session_id}},
    )


async def run_crewai_crew(session_id: str) -> dict:
    """CrewAI 2-agent crew, both also targeting SHARED_PATH."""
    from crewai import Agent, Task, Crew, LLM
    crewai_llm = LLM(
        model="anthropic/claude-haiku-4-5-20251001",
        api_key=os.environ["ANTHROPIC_API_KEY"],
    )
    perf = Agent(role="performance_engineer",
                 goal=f"Add caching to {SHARED_PATH}",
                 backstory="Caching specialist.",
                 llm=crewai_llm, verbose=False, allow_delegation=False)
    obs = Agent(role="observability_engineer",
                goal=f"Add metrics to {SHARED_PATH}",
                backstory="Metrics specialist.",
                llm=crewai_llm, verbose=False, allow_delegation=False)
    t_perf = Task(
        description=f"Output a 3-line caching decorator for functions in {SHARED_PATH}. Code only.",
        expected_output=f"A caching decorator for {SHARED_PATH}.",
        agent=perf,
    )
    t_obs = Task(
        description=f"Output a 3-line metrics decorator for functions in {SHARED_PATH}. Code only.",
        expected_output=f"A metrics decorator for {SHARED_PATH}.",
        agent=obs,
    )
    crew = Crew(agents=[perf, obs], tasks=[t_perf, t_obs], verbose=False)
    return await asyncio.to_thread(crew.kickoff)


async def main():
    print("=== Week 3 full integration test: LangGraph + CrewAI on the same Synapse stack ===")
    await apply_migrations()

    session_id = f"v02_w3full_{uuid.uuid4().hex[:6]}"

    # Single Synapse install for the whole process — both adapters share
    # the same session, bus, and state graph.
    import synapse
    synapse.set_llm(synapse.from_anthropic(model="claude-haiku-4-5-20251001"))
    synapse.install(
        bus_url=REDIS_URL,
        state_dsn=PG_DSN,
        session_id=session_id,
        framework="langgraph",
    )
    # Also install CrewAI alongside (multiple framework adapters can coexist)
    synapse.install(
        framework="crewai",
        session_id=session_id,
        auto=False,
    )
    print(f"  session: {session_id}")
    print(f"  installed frameworks: langgraph + crewai")

    # Start the L2 router
    from synapse.bus import Bus
    from synapse.state import StateGraph
    from runtime.router.worker import Router

    bus = Bus(REDIS_URL)
    state = StateGraph(PG_DSN)
    await bus.connect()
    await state.connect()
    router = Router(bus, state, session_id, consumer="v02_w3full_router")
    router_task = asyncio.create_task(router.run())
    await asyncio.sleep(0.4)

    from anthropic import AsyncAnthropic
    anthropic_client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    started = time.time()

    # Run the LangGraph crew first — it writes to auth.py twice
    print("  running LangGraph crew...")
    try:
        await run_langgraph_crew(session_id, anthropic_client)
    except Exception as e:
        print(f"  langgraph crew error: {e}")

    # Then run the CrewAI crew — its writes will see LangGraph's recent
    # work as stale-base overwrites.
    print("  running CrewAI crew...")
    try:
        await run_crewai_crew(session_id)
    except Exception as e:
        print(f"  crewai crew error: {e}")

    elapsed = time.time() - started
    await asyncio.sleep(0.8)
    router.stop()
    try:
        await asyncio.wait_for(router_task, timeout=2)
    except asyncio.TimeoutError:
        router_task.cancel()

    intent_rows = await state.pool.fetch(
        "SELECT id, agent_id, scope, status FROM intentions WHERE session_id=$1 ORDER BY created_at",
        session_id,
    )
    agent_rows = await state.pool.fetch(
        "SELECT id FROM agents WHERE session_id=$1", session_id,
    )
    redis = bus.redis
    stream_entries = await redis.xrange(f"synapse:session:{session_id}:events", count=200)

    conflict_count = 0
    cross_framework_conflicts = 0
    for r in agent_rows:
        entries = await redis.xrange(f"synapse:agent:{r['id']}:inbox", count=20)
        for _eid, fields in entries:
            try:
                env = json.loads(fields["e"])
                if env["type"] == "CONFLICT":
                    conflict_count += 1
                    # Cross-framework if the conflicting intentions are
                    # from agents whose names match different frameworks
                    conflicting_agents = [
                        ci["agent_id"]
                        for ci in env["payload"].get("conflicting_intentions", [])
                    ]
                    target = env["payload"].get("intention_id", "")
                    # Find the target intention's agent
                    if any(a.startswith("lg_") for a in conflicting_agents) and \
                       any("engineer" in a for a in conflicting_agents + [r["id"]]):
                        cross_framework_conflicts += 1
            except Exception:
                pass

    await bus.close()
    await state.close()

    # Identify which agents came from which framework
    agent_ids = sorted(r["id"] for r in agent_rows)
    lg_agents = [a for a in agent_ids if a.startswith("lg_")]
    crewai_agents = [a for a in agent_ids if "engineer" in a]

    print()
    print("--- summary ---")
    print(f"  elapsed:                   {elapsed:.1f}s")
    print(f"  total agents persisted:    {len(agent_rows)}  ({agent_ids})")
    print(f"    - LangGraph agents:      {lg_agents}")
    print(f"    - CrewAI agents:         {crewai_agents}")
    print(f"  intentions persisted:      {len(intent_rows)}")
    print(f"  envelopes on stream:       {len(stream_entries)}")
    print(f"  CONFLICT envelopes total:  {conflict_count}")
    print(f"  cross-framework conflicts: {cross_framework_conflicts}")

    return {
        "session_id": session_id,
        "elapsed_seconds": round(elapsed, 2),
        "agents_persisted": len(agent_rows),
        "agent_ids": agent_ids,
        "lg_agents": lg_agents,
        "crewai_agents": crewai_agents,
        "intentions_persisted": len(intent_rows),
        "envelopes_on_stream": len(stream_entries),
        "conflicts_detected": conflict_count,
        "cross_framework_conflicts": cross_framework_conflicts,
    }


if __name__ == "__main__":
    result = asyncio.run(main())
    print("\n--- result.json ---")
    print(json.dumps(result, indent=2))
