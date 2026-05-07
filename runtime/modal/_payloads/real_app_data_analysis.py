"""Real product-dev test: 4 data-team agents collaboratively building a
sales analysis + visualization report.

Realistic data-team workflow — different from a coding workflow because
the artifacts are dataframe transformations and the natural collisions
are on column names + derived features, not file paths.

Roles + planned tasks:

  data_loader:
    load_raw         (read sales CSV, define `df` shape)
    schema_doc       (write column dictionary describing what each col means)

  data_cleaner:
    rename_columns   (standardize column names — touches the SAME column
                      vocabulary the loader just defined)
    drop_nulls       (filter rows; defines a cleaned df)
    derive_revenue   (** OVERLAPS analyst ** — adds `revenue` column)

  analyst:
    derive_revenue   (** OVERLAPS cleaner ** — same `revenue` column,
                      different formula)
    monthly_summary  (groupby month -> total revenue)
    top_products     (top-10 by revenue)

  visualizer:
    plot_monthly     (line chart of monthly revenue — depends on analyst's
                      monthly_summary)
    plot_top_products(bar chart - depends on top_products)
    style_palette    (** OVERLAPS data_cleaner.rename_columns ** — picks
                      display names, which collide with cleaner's standardized
                      names if both teams pick different conventions)

Natural collisions (scope = `analysis.dataset.<feature>:w`):
  - analysis.dataset.column_names:w  -> data_cleaner + visualizer
  - analysis.dataset.revenue:w       -> data_cleaner + analyst
"""
import asyncio
import json
import os
import random
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


# Each task is (task_name, scope_features, prompt). scope_features list maps
# to scope claims like `analysis.dataset.<feature>:w`.
PLAN = {
    "data_loader": [
        ("load_raw", ["raw_df"],
         "You are a data engineer. Write 4-8 lines of Python that load a "
         "sales CSV at /tmp/sales.csv into a pandas DataFrame `df`, then "
         "print df.shape and df.columns.tolist(). Output ONLY the Python "
         "code, no prose."),
        ("schema_doc", ["schema"],
         "Write a Python dict `SCHEMA` mapping each of these column names to "
         "a one-line description: order_id, customer_id, sku, product_name, "
         "quantity, unit_price, order_date. Output ONLY the dict, no prose."),
    ],
    "data_cleaner": [
        ("rename_columns", ["column_names"],
         "Write 3-6 lines of Python that rename pandas DataFrame columns to "
         "snake_case. Use df.rename(columns=...). Specifically: 'OrderID' -> "
         "'order_id', 'CustomerID' -> 'customer_id', 'OrderDate' -> 'order_date'. "
         "Output ONLY the code, no prose."),
        ("drop_nulls", ["cleaned_df"],
         "Write 2-4 lines of Python that drop rows where order_id, customer_id, "
         "or order_date is null. Use df.dropna(subset=...). Output ONLY the code."),
        ("derive_revenue", ["revenue"],
         "Write 1-3 lines of Python that add a `revenue` column to df by "
         "multiplying quantity by unit_price. Output ONLY the code."),
    ],
    "analyst": [
        ("derive_revenue", ["revenue"],
         "Write 1-3 lines of Python adding a `revenue` column = quantity * "
         "unit_price * (1 - discount). Output ONLY the code, no prose."),
        ("monthly_summary", ["monthly"],
         "Write 2-5 lines of Python that group df by month (extracted from "
         "order_date) and sum revenue. Result: `monthly`. Output ONLY code."),
        ("top_products", ["top_products"],
         "Write 2-5 lines of Python that compute top 10 SKUs by total revenue. "
         "Result: `top_products`. Output ONLY code."),
    ],
    "visualizer": [
        ("plot_monthly", ["plots.monthly"],
         "Write 4-7 lines of matplotlib code that plots `monthly` as a line "
         "chart with x=month, y=revenue. Save to /tmp/monthly.png. Output ONLY code."),
        ("plot_top_products", ["plots.top_products"],
         "Write 4-7 lines of matplotlib code that plots `top_products` as a "
         "horizontal bar chart. Save to /tmp/top.png. Output ONLY code."),
        ("style_palette", ["column_names"],
         "Write a Python dict DISPLAY_NAMES mapping these column names to "
         "human-readable labels: 'OrderID' -> 'Order #', 'CustomerID' -> "
         "'Customer', 'OrderDate' -> 'Date'. Output ONLY the dict."),
    ],
}


def scope_for(features: list[str]) -> list[str]:
    return [f"analysis.dataset.{f}:w" for f in features]


async def apply_migrations() -> None:
    import asyncpg
    conn = await asyncpg.connect(PG_DSN)
    try:
        await conn.execute(MIGRATIONS_SQL)
    finally:
        await conn.close()


async def agent_workflow(agent_id, session_id, plan, notebook_dir, ant, with_synapse):
    """Run one agent's workflow: real LLM calls + write each cell."""
    from synapse.integrations.hermes_integration import wrap_tool_call_for_synapse

    results = []
    for task_name, features, prompt in plan:
        await asyncio.sleep(random.uniform(0.0, 0.15))
        msg = await ant.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        content = msg.content[0].text if msg.content else ""
        cell_path = os.path.join(notebook_dir, f"{agent_id}_{task_name}.py")

        async def actual_write(p=cell_path, body=content, fs=features):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(body)
            return {
                "wrote_bytes": len(body),
                "scope_features": fs,
            }

        if with_synapse:
            # Each task claims one scope per feature it touches
            tool_result = await wrap_tool_call_for_synapse(
                "edit_notebook",
                {"task": task_name, "features": features},
                actual_write,
                agent_id=agent_id,
            )
            # We pass a custom scope via the integration's _scope_from_tool_call,
            # but the default scope mapping doesn't know about analysis.dataset
            # paths. Simpler: emit a second explicit intention with the right
            # scope. Actually, simpler still: monkey-patch by emitting via the
            # agent directly for accurate scope. Use the registered agent.
        else:
            tool_result = await actual_write()

        results.append({
            "task": task_name,
            "scope_features": features,
            "tool_result": tool_result,
            "tokens_in": msg.usage.input_tokens,
            "tokens_out": msg.usage.output_tokens,
            "content_excerpt": content[:120],
        })
    return {"agent_id": agent_id, "tasks": results}


async def emit_with_explicit_scope(
    agent, action_desc, scope, expected, gate_ms, inner
):
    """Helper: emit INTENTION with our analysis-shaped scope, then run."""
    intent_id, conflicts = await agent.emit_intention(
        action={"task": action_desc},
        scope=scope,
        expected_outcome=expected,
        blocking=True,
        gate_ms=gate_ms,
    )
    outcome = "success"
    err_state = None
    try:
        return await inner()
    except Exception as e:
        outcome = "failure"
        err_state = {"error": str(e)[:200]}
        raise
    finally:
        await agent.emit_resolution(
            intention_id=intent_id, outcome=outcome,
            state_diff=err_state or {},
        )


async def agent_workflow_v2(agent_id, session_id, plan, notebook_dir, ant, with_synapse, runtime_agents):
    """Use explicit-scope INTENTION emission (analysis.dataset.<feature>:w).

    Skips the integration wrapper because that one defaults to repo.fs.<path>
    scope which is the wrong shape for data-analysis tasks.
    """
    results = []
    agent = runtime_agents.get(agent_id) if with_synapse else None
    for task_name, features, prompt in plan:
        await asyncio.sleep(random.uniform(0.0, 0.15))
        msg = await ant.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        content = msg.content[0].text if msg.content else ""
        cell_path = os.path.join(notebook_dir, f"{agent_id}_{task_name}.py")

        async def actual_write(p=cell_path, body=content):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(body)
            return {"wrote_bytes": len(body)}

        scope = scope_for(features)
        if with_synapse and agent is not None:
            tool_result = await emit_with_explicit_scope(
                agent, f"{agent_id}:{task_name}", scope,
                f"analysis:{task_name}", 400, actual_write,
            )
        else:
            tool_result = await actual_write()

        results.append({
            "task": task_name,
            "scope_features": features,
            "tool_result": tool_result,
            "tokens_in": msg.usage.input_tokens,
            "tokens_out": msg.usage.output_tokens,
            "content_excerpt": content[:140],
        })
    return {"agent_id": agent_id, "tasks": results}


async def run_scenario(with_synapse: bool):
    label = "with_synapse" if with_synapse else "no_synapse"
    print(f"\n=== mode: {label} ===")

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
    session_id = f"data_{label}_{uuid.uuid4().hex[:8]}"
    notebook_dir = f"/tmp/data_notebook_{label}_{uuid.uuid4().hex[:6]}"
    os.makedirs(notebook_dir, exist_ok=True)

    router_task = None
    runtime_agents = {}
    if with_synapse:
        await install_hermes_synapse_hooks(
            bus=bus, state=state, session_id=session_id,
            agent_id="data_loader", gate_ms=400,
        )
        for aid in ("data_cleaner", "analyst", "visualizer"):
            await register_synapse_agent(aid)
        runtime_agents = dict(_hermes_runtime["agents"])
        from runtime.router.worker import Router

        router = Router(bus, state, session_id, consumer="data_router")
        router_task = asyncio.create_task(router.run())
        await asyncio.sleep(0.4)
    else:
        _hermes_runtime.clear()

    ant = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    started = time.time()
    agent_results = await asyncio.gather(
        *[
            agent_workflow_v2(aid, session_id, plan, notebook_dir, ant, with_synapse, runtime_agents)
            for aid, plan in PLAN.items()
        ],
        return_exceptions=True,
    )
    elapsed = time.time() - started
    await asyncio.sleep(0.8)

    if router_task is not None:
        # Stop the router
        for t in [router_task]:
            t.cancel()
            try:
                await asyncio.wait_for(t, timeout=2)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

    intent_rows = []
    agent_rows = []
    stream_entries = []
    inbox_entries = []
    conflict_count = 0
    conflict_kinds = {"scope_overlap": 0, "stale_base_overwrite": 0}
    if with_synapse:
        intent_rows = await state.pool.fetch(
            "SELECT id, agent_id, scope, status FROM intentions WHERE session_id = $1 ORDER BY created_at",
            session_id,
        )
        agent_rows = await state.pool.fetch(
            "SELECT id FROM agents WHERE session_id = $1", session_id,
        )
        redis = bus.redis
        stream_entries = await redis.xrange(
            f"synapse:session:{session_id}:events", count=200,
        )
        for r in agent_rows:
            entries = await redis.xrange(
                f"synapse:agent:{r['id']}:inbox", count=50,
            )
            inbox_entries.extend([(r["id"], e) for e in entries])
        for _aid, (eid, fields) in inbox_entries:
            try:
                env = json.loads(fields["e"])
                if env["type"] == "CONFLICT":
                    conflict_count += 1
                    k = env["payload"].get("kind", "?")
                    conflict_kinds[k] = conflict_kinds.get(k, 0) + 1
            except Exception:
                pass

    # Identify which scope features were touched by multiple agents
    feature_writers: dict[str, list[str]] = {}
    for r in agent_results:
        if not isinstance(r, dict):
            continue
        for t in r["tasks"]:
            for f in t["scope_features"]:
                feature_writers.setdefault(f, []).append(r["agent_id"])
    contended_features = {
        f: aids for f, aids in feature_writers.items()
        if len(set(aids)) > 1
    }

    tokens_in = sum(
        t.get("tokens_in", 0)
        for r in agent_results if isinstance(r, dict)
        for t in r["tasks"]
    )
    tokens_out = sum(
        t.get("tokens_out", 0)
        for r in agent_results if isinstance(r, dict)
        for t in r["tasks"]
    )
    total_steps = sum(len(r["tasks"]) for r in agent_results if isinstance(r, dict))

    print(f"  elapsed:                    {elapsed:.1f}s")
    print(f"  agents:                     {len(PLAN)}")
    print(f"  total task steps:           {total_steps}")
    print(f"  unique features touched:    {len(feature_writers)}")
    print(f"  contended features:         {len(contended_features)}")
    for f, aids in contended_features.items():
        print(f"      {f:25s} <- {sorted(set(aids))}")
    print(f"  tokens in/out:              {tokens_in}/{tokens_out}")
    print(f"  envelopes on bus stream:    {len(stream_entries)}")
    print(f"  intentions persisted (PG):  {len(intent_rows)}")
    print(f"  agents persisted (PG):      {len(agent_rows)}")
    print(f"  CONFLICT envelopes routed:  {conflict_count}")
    print(f"  CONFLICT kinds:             {conflict_kinds}")

    await bus.close()
    await state.close()

    return {
        "mode": label,
        "session_id": session_id,
        "elapsed_seconds": round(elapsed, 2),
        "total_steps": total_steps,
        "unique_features": len(feature_writers),
        "contended_features": {f: sorted(set(a)) for f, a in contended_features.items()},
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "envelopes_on_stream": len(stream_entries),
        "intentions_persisted": len(intent_rows),
        "agents_persisted": len(agent_rows),
        "conflicts_detected": conflict_count,
        "conflict_kinds": conflict_kinds,
        "agent_results": [
            r if isinstance(r, dict) else {"error": str(r)} for r in agent_results
        ],
    }


async def main():
    print("=== REAL multi-agent data analysis pipeline product-dev test ===")
    await apply_migrations()
    no_syn = await run_scenario(with_synapse=False)
    with_syn = await run_scenario(with_synapse=True)
    print("\n--- summary ---")
    print(f"  no_synapse:    steps={no_syn['total_steps']}  "
          f"contended_features={len(no_syn['contended_features'])}  "
          f"conflicts_caught={no_syn['conflicts_detected']}")
    print(f"  with_synapse:  steps={with_syn['total_steps']}  "
          f"contended_features={len(with_syn['contended_features'])}  "
          f"conflicts_caught={with_syn['conflicts_detected']}  "
          f"kinds={with_syn['conflict_kinds']}  "
          f"envelopes={with_syn['envelopes_on_stream']}")
    return {"no_synapse": no_syn, "with_synapse": with_syn}


if __name__ == "__main__":
    result = asyncio.run(main())
    print("\n--- result.json ---")
    print(json.dumps(result, indent=2)[:8000])  # cap to keep output manageable
