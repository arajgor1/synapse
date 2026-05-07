"""Week-2 live test: real LangGraph + real Anthropic Haiku + Synapse v0.2.

Spins up a 3-line Synapse install in front of a small LangGraph multi-agent
graph. The graph has 3 agent nodes that each call a `write_file` tool. The
3 calls deliberately target the same file so the L2 router (configured via
`synapse.install`) catches sequential overwrites via the `stale_base_overwrite`
kind we added in v0.1's late phase.

This is the Week-2 success metric:
  > "LangGraph user wires Synapse in 3 lines and sees live conflicts in
  >  their dashboard"

Three lines = the import + set_llm + install. Everything else is the
user's normal LangGraph code.
"""
import asyncio
import json
import os
import sys
import time
import uuid

# Run LangChain async callbacks INLINE (not on a background thread). Without
# this, callbacks fire on a separate event loop and any async work they kick
# off can't reuse the main loop's bus/state-graph connections.
os.environ["LANGCHAIN_CALLBACKS_BACKGROUND"] = "false"

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


def build_langgraph(session_id, anthropic_client):
    """Build a 3-agent LangGraph state graph that writes to a shared file.

    Each agent makes a real Anthropic call to generate code, then invokes
    a `write_file` tool — same scope (repo.fs.shared.py:w) every time.
    """
    from langchain_core.tools import tool
    from langgraph.graph import StateGraph, END
    from typing import TypedDict

    @tool
    def write_file(path: str, content: str) -> str:
        """Write content to a file path. Returns confirmation."""
        full = f"/tmp/{path}"
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        existed = os.path.exists(full)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        return f"wrote {len(content)} bytes to {path} (overwrote={existed})"

    class GraphState(TypedDict):
        outputs: dict

    async def call_agent(role, prompt):
        msg = await anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text if msg.content else ""
        return text, msg.usage.input_tokens, msg.usage.output_tokens

    async def agent_a(state: GraphState):
        text, tin, tout = await call_agent(
            "agent_a",
            "Write a Python class `Config` with fields debug:bool=False, "
            "host:str='localhost', port:int=8080. Output ONLY the class, no markdown.",
        )
        # Invoke the tool so LangChain's callback pipeline fires
        result = await write_file.ainvoke(
            {"path": "shared.py", "content": text},
            config={"metadata": {"agent_name": "agent_a", "session_id": session_id}},
        )
        return {"outputs": {**state.get("outputs", {}), "agent_a": {"text": text, "result": result, "tokens_in": tin, "tokens_out": tout}}}

    async def agent_b(state: GraphState):
        text, tin, tout = await call_agent(
            "agent_b",
            "Write a Python class `Config` with fields verbose:bool=True, "
            "endpoint:str='https://api.x.com'. Output ONLY the class, no markdown.",
        )
        result = await write_file.ainvoke(
            {"path": "shared.py", "content": text},
            config={"metadata": {"agent_name": "agent_b", "session_id": session_id}},
        )
        return {"outputs": {**state.get("outputs", {}), "agent_b": {"text": text, "result": result, "tokens_in": tin, "tokens_out": tout}}}

    async def agent_c(state: GraphState):
        text, tin, tout = await call_agent(
            "agent_c",
            "Write a Python class `Config` with fields api_key:str, region:str='us-east-1'. "
            "Output ONLY the class, no markdown.",
        )
        result = await write_file.ainvoke(
            {"path": "shared.py", "content": text},
            config={"metadata": {"agent_name": "agent_c", "session_id": session_id}},
        )
        return {"outputs": {**state.get("outputs", {}), "agent_c": {"text": text, "result": result, "tokens_in": tin, "tokens_out": tout}}}

    builder = StateGraph(GraphState)
    builder.add_node("agent_a", agent_a)
    builder.add_node("agent_b", agent_b)
    builder.add_node("agent_c", agent_c)
    builder.set_entry_point("agent_a")
    builder.add_edge("agent_a", "agent_b")
    builder.add_edge("agent_b", "agent_c")
    builder.add_edge("agent_c", END)
    return builder.compile()


async def run(with_synapse: bool):
    """Run the same LangGraph with vs. without Synapse.install()."""
    label = "with_synapse" if with_synapse else "no_synapse"
    print(f"\n=== mode: {label} ===")

    session_id = f"v02_lg_{label}_{uuid.uuid4().hex[:6]}"

    from anthropic import AsyncAnthropic
    anthropic_client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    router_task = None
    bus = None
    state = None

    if with_synapse:
        # The Week-2 "3 lines" test
        import synapse
        synapse.set_llm(synapse.from_anthropic(anthropic_client))
        result = synapse.install(
            framework="langgraph",
            bus_url=REDIS_URL,
            state_dsn=PG_DSN,
            session_id=session_id,
        )
        print(f"  synapse.install -> {result}")

        # Start the L2 router in-process so CONFLICTs get routed to inboxes
        from synapse.bus import Bus
        from synapse.state import StateGraph
        from runtime.router.worker import Router

        bus = Bus(REDIS_URL)
        state = StateGraph(PG_DSN)
        await bus.connect()
        await state.connect()
        router = Router(bus, state, session_id, consumer="v02_lg_router")
        router_task = asyncio.create_task(router.run())
        await asyncio.sleep(0.4)

    graph = build_langgraph(session_id, anthropic_client)

    # The Week-2 success-metric test: attach the Synapse callback handler
    # to the graph invocation. (LangChain's global callback registry has
    # changed across versions — explicit attach is the most reliable path
    # and matches the "3 lines + your normal LangGraph code" pitch.)
    if with_synapse:
        from synapse.frameworks.langgraph import get_callback
        cb = get_callback()
        config = {"callbacks": [cb], "metadata": {"session_id": session_id}}
    else:
        config = {}

    started = time.time()
    final_state = await graph.ainvoke({"outputs": {}}, config=config)
    elapsed = time.time() - started

    # Let coordinator/router catch up
    await asyncio.sleep(0.6)

    if router_task is not None:
        router.stop()
        try:
            await asyncio.wait_for(router_task, timeout=2)
        except asyncio.TimeoutError:
            router_task.cancel()

    # Inspect what landed in Postgres + Redis
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

    # Inspect the final shared.py to see whose work survived
    try:
        with open("/tmp/shared.py", encoding="utf-8") as f:
            final_text = f.read()
    except FileNotFoundError:
        final_text = "(no file)"

    outputs = final_state.get("outputs", {})
    tokens_in = sum(o.get("tokens_in", 0) for o in outputs.values())
    tokens_out = sum(o.get("tokens_out", 0) for o in outputs.values())

    print(f"  elapsed:                 {elapsed:.1f}s")
    print(f"  agents that ran:         {len(outputs)}/3")
    print(f"  total tokens in/out:     {tokens_in}/{tokens_out}")
    print(f"  envelopes on stream:     {stream_count}")
    print(f"  intentions persisted:    {len(intent_rows)}")
    print(f"  agents persisted:        {len(agent_rows)}")
    print(f"  CONFLICT envelopes:      {conflict_count}")
    print(f"  final shared.py first line: {(final_text.splitlines() or [''])[0][:80]!r}")

    return {
        "mode": label,
        "session_id": session_id,
        "elapsed_seconds": round(elapsed, 2),
        "agents_ran": len(outputs),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "envelopes_on_stream": stream_count,
        "intentions_persisted": len(intent_rows),
        "agents_persisted": len(agent_rows),
        "conflicts_detected": conflict_count,
        "final_first_line": (final_text.splitlines() or [""])[0],
    }


async def main():
    print("=== v0.2 Week 2 live test: LangGraph + synapse.install() ===")
    await apply_migrations()
    no_syn = await run(with_synapse=False)
    with_syn = await run(with_synapse=True)

    print("\n--- summary ---")
    print(f"  no_synapse:    conflicts_caught={no_syn['conflicts_detected']}  envelopes={no_syn['envelopes_on_stream']}")
    print(f"  with_synapse:  conflicts_caught={with_syn['conflicts_detected']}  envelopes={with_syn['envelopes_on_stream']}  intentions={with_syn['intentions_persisted']}  agents={with_syn['agents_persisted']}")

    return {"no_synapse": no_syn, "with_synapse": with_syn}


if __name__ == "__main__":
    result = asyncio.run(main())
    print("\n--- result.json ---")
    print(json.dumps(result, indent=2))
