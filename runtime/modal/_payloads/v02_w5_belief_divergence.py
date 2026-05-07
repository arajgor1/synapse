"""Week 5 live test: BELIEF divergence catches semantic conflicts that
scope-overlap detection misses.

The setup:
  - 3 data-team agents (cleaner, analyst, finance_lead)
  - Each writes to a DIFFERENT file (zero scope overlap)
  - But each computes ``revenue`` differently:
      cleaner       : revenue = qty * price
      analyst       : revenue = qty * price * (1 - discount)
      finance_lead  : revenue = qty * price - returns
  - synapse.install(emit_beliefs_from_tool_results=True) auto-extracts
    `revenue_formula` from each tool result via BYO-LLM.
  - When agent #2's belief is emitted, live divergence detection fires.

The headline: BELIEF divergence detected on 'revenue_formula' across
3 agents and 3 distinct values, even though no scope-overlap conflict
was ever raised.
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

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logging.getLogger("synapse").setLevel(logging.INFO)

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
    " CREATE TABLE IF NOT EXISTS beliefs ("
    " agent_id text NOT NULL, session_id text NOT NULL, tenant_id text,"
    " key text NOT NULL, value jsonb NOT NULL,"
    " confidence real NOT NULL CHECK (confidence BETWEEN 0 AND 1),"
    " source text NOT NULL CHECK (source IN ('observed','inferred','assumed')),"
    " evidence text, updated_at timestamptz NOT NULL DEFAULT now(),"
    " PRIMARY KEY (agent_id, key)"
    ");"
)

# 3 agents, 3 different files (no scope overlap), 3 different revenue formulas
PROMPTS = {
    "cleaner": (
        "src/cleaner.py",
        "Write a 5-line Python function `clean_revenue(rows)` that returns "
        "rows with a new `revenue` column = `qty * price`. Use simple math, "
        "no discount logic. Output ONLY the code, no markdown."
    ),
    "analyst": (
        "src/analyst.py",
        "Write a 5-line Python function `compute_revenue(rows)` that returns "
        "rows with `revenue` = `qty * price * (1 - discount)`. The discount "
        "factor is critical. Output ONLY the code, no markdown."
    ),
    "finance_lead": (
        "src/finance.py",
        "Write a 5-line Python function `report_revenue(rows)` that computes "
        "`revenue` as `qty * price - returns`. Net of returns. "
        "Output ONLY the code, no markdown."
    ),
}


async def apply_migrations():
    import asyncpg
    conn = await asyncpg.connect(PG_DSN)
    try:
        await conn.execute(MIGRATIONS_SQL)
    finally:
        await conn.close()


async def agent_step(agent_id, session_id, write_path, prompt, ant, mode: str):
    """Real LLM call + write through synapse.intend with BELIEF auto-extract on success."""
    import synapse

    msg = await ant.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    content = msg.content[0].text if msg.content else ""

    if mode == "no_synapse":
        os.makedirs(os.path.dirname(write_path) or ".", exist_ok=True)
        with open(write_path, "w", encoding="utf-8") as f:
            f.write(content)
        return {
            "agent_id": agent_id,
            "tokens_in": msg.usage.input_tokens,
            "tokens_out": msg.usage.output_tokens,
            "wrote_bytes": len(content),
            "beliefs_emitted": [],
            "divergences": [],
        }

    # Synapse mode — different file path per agent (NO scope overlap)
    proposed = {"path": write_path, "content": content, "tool": "write_file"}
    async with synapse.intend(
        scope=[f"repo.fs.{write_path}:w"],
        agent=agent_id,
        session=session_id,
        expected_outcome=f"{agent_id} writes {write_path}",
        blocking=True,
        gate_ms=200,
        proposed_action=proposed,
    ) as i:
        os.makedirs(os.path.dirname(write_path) or ".", exist_ok=True)
        with open(write_path, "w", encoding="utf-8") as f:
            f.write(content)
        i.set_state_diff({"content": content[:1500], "wrote_bytes": len(content)})

    return {
        "agent_id": agent_id,
        "tokens_in": msg.usage.input_tokens,
        "tokens_out": msg.usage.output_tokens,
        "wrote_bytes": len(content),
        "beliefs_emitted": list(i.beliefs_emitted),
        "divergences": list(i.divergences),
    }


async def run(mode: str):
    label = mode
    print(f"\n=== mode: {label} ===")

    session_id = f"v02_w5_{label}_{uuid.uuid4().hex[:6]}"
    repo_root = f"/tmp/dataops_w5_{label}_{uuid.uuid4().hex[:4]}"

    from anthropic import AsyncAnthropic
    ant = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    bus = state = router_task = None

    if mode != "no_synapse":
        import synapse
        synapse.set_llm(synapse.from_anthropic(ant, model="claude-haiku-4-5-20251001"))
        result = synapse.install(
            bus_url=REDIS_URL,
            state_dsn=PG_DSN,
            session_id=session_id,
            emit_beliefs_from_tool_results=(mode == "with_synapse_beliefs"),
        )
        print(f"  synapse.install -> {result}")

        from synapse.bus import Bus
        from synapse.state import StateGraph
        from runtime.router.worker import Router

        bus = Bus(REDIS_URL)
        state = StateGraph(PG_DSN)
        await bus.connect()
        await state.connect()
        router = Router(bus, state, session_id, consumer="v02_w5_router")
        router_task = asyncio.create_task(router.run())
        await asyncio.sleep(0.4)
    else:
        try:
            from synapse.intend import _runtime
            _runtime.clear()
        except Exception:
            pass

    started = time.time()
    results = []
    for agent_id, (rel_path, prompt) in PROMPTS.items():
        write_path = f"{repo_root}/{rel_path}"
        try:
            r = await agent_step(agent_id, session_id, write_path, prompt, ant, mode)
        except Exception as e:
            r = {"agent_id": agent_id, "error": str(e)}
        results.append(r)
        await asyncio.sleep(0.4)
    elapsed = time.time() - started

    await asyncio.sleep(0.6)
    if router_task is not None:
        router.stop()
        try:
            await asyncio.wait_for(router_task, timeout=2)
        except asyncio.TimeoutError:
            router_task.cancel()

    # End-of-run inspection
    intent_rows = []
    belief_rows = []
    final_divergences = []
    if mode != "no_synapse" and state is not None and bus is not None:
        intent_rows = await state.pool.fetch(
            "SELECT id, agent_id, scope, status FROM intentions WHERE session_id=$1",
            session_id,
        )
        belief_rows = await state.pool.fetch(
            "SELECT agent_id, key, value, confidence, source FROM beliefs WHERE session_id=$1",
            session_id,
        )
        # Final divergence list across the whole session
        import synapse
        final_divergences = [d.to_dict() for d in await synapse.list_divergences(session_id=session_id)]

    if bus is not None:
        await bus.close()
    if state is not None:
        await state.close()

    tokens_in = sum(r.get("tokens_in", 0) for r in results)
    tokens_out = sum(r.get("tokens_out", 0) for r in results)
    total_beliefs = sum(len(r.get("beliefs_emitted", [])) for r in results)
    live_divergences = sum(len(r.get("divergences", [])) for r in results)

    print(f"  elapsed:                 {elapsed:.1f}s")
    print(f"  tokens in/out:           {tokens_in}/{tokens_out}")
    print(f"  intentions persisted:    {len(intent_rows)}")
    print(f"  beliefs in state graph:  {len(belief_rows)}")
    if belief_rows:
        for r in belief_rows:
            print(f"    {r['agent_id']:14s} {r['key']!r:25s} = {r['value']!s:60s}")
    print(f"  beliefs emitted (live):  {total_beliefs}")
    print(f"  live divergences:        {live_divergences}")
    print(f"  final divergences:       {len(final_divergences)}")
    for d in final_divergences:
        print(f"    {d['key']!r}: {len(d['distinct_values'])} distinct value(s) "
              f"across {len(d['agents_involved'])} agent(s) (severity={d['severity']:.2f})")

    return {
        "mode": label,
        "session_id": session_id,
        "elapsed_seconds": round(elapsed, 2),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "intentions_persisted": len(intent_rows),
        "beliefs_persisted": len(belief_rows),
        "belief_rows": [dict(r) for r in belief_rows],
        "live_divergences_caught": live_divergences,
        "final_divergences": final_divergences,
        "agent_results": results,
    }


async def main():
    print("=== v0.2 Week 5 live test: BELIEF divergence (semantic conflicts) ===")
    await apply_migrations()
    no_syn = await run("no_synapse")
    with_syn = await run("with_synapse")  # default — no belief emission
    with_beliefs = await run("with_synapse_beliefs")  # emit_beliefs flag on

    print("\n--- summary ---")
    print(f"  no_synapse:               beliefs=0  divergences=0  (no scope overlap, scope-only is blind)")
    print(f"  with_synapse (default):   beliefs={with_syn['beliefs_persisted']}  divergences={len(with_syn['final_divergences'])}")
    print(f"  with_synapse_beliefs:     beliefs={with_beliefs['beliefs_persisted']}  divergences_caught={with_beliefs['live_divergences_caught']}  final={len(with_beliefs['final_divergences'])}")

    return {
        "no_synapse": no_syn,
        "with_synapse": with_syn,
        "with_synapse_beliefs": with_beliefs,
    }


if __name__ == "__main__":
    result = asyncio.run(main())
    print("\n--- result.json ---")
    # Trim agent_results.beliefs_emitted to keep output manageable
    print(json.dumps(result, indent=2, default=str)[:6000])
