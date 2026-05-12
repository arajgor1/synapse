"""Public benchmark v17 — cross-framework value demonstration.

Runs the SAME 3-agent divergent-prompt pattern (architect/backend/tester
each told to use a different field name for the same Todo model) under
each of 4 framework adapters, comparing no_synapse vs with_synapse for
each:

  1. Hermes    (already proven in product_dev_hermes; replicated here)
  2. AutoGen   (RoundRobin / parallel agents)
  3. CrewAI    (Crew with 3 agents)
  4. LangGraph (3 parallel react agents)

Per-framework, per-mode metrics:
  - distinct_field_names: how many naming conventions ended up persisted
  - conflicts_detected:   how many CONFLICT envelopes routed (with_synapse only)
  - intentions_persisted: how many rows in the Postgres intentions table
  - envelopes_on_stream:  total INTENTION + CONFLICT + RESOLUTION envelopes
  - alignment:            1/N where N = distinct_field_names (1.0 = full agreement, lower = more divergence)

The value claim: with_synapse mode produces a *traceable audit trail* of
the disagreement; no_synapse mode silently loses 2/3 of the agents' work.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import traceback
from typing import Any

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("DO_NOT_TRACK", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

sys.path.insert(0, "/opt/synapse-sdk")
sys.path.insert(0, "/opt")

REDIS_URL = "redis://localhost:6379/0"
PG_DSN = "postgresql://synapse:synapse_dev@localhost:5432/synapse"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"


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
    " CREATE INDEX IF NOT EXISTS intentions_scope_gin ON intentions USING GIN (scope);"
)


async def apply_migrations() -> None:
    import asyncpg
    conn = await asyncpg.connect(PG_DSN)
    try:
        await conn.execute(MIGRATIONS_SQL)
    finally:
        await conn.close()


FIELD_PATTERNS = {
    "description": re.compile(r"\bdescription\b\s*[:=]"),
    "task":        re.compile(r"\btask\b\s*[:=]"),
    "content":     re.compile(r"\bcontent\b\s*[:=]"),
}


def analyze_outputs(outputs: list[str]) -> dict:
    """Given 3 agent outputs, count how many distinct body-field names
    were produced. Returns alignment + per-agent fields."""
    per_agent = []
    distinct: set[str] = set()
    for text in outputs:
        agent_fields = [n for n, pat in FIELD_PATTERNS.items() if pat.search(text or "")]
        per_agent.append(",".join(agent_fields) or "?")
        distinct.update(agent_fields)
    n = len(distinct)
    alignment = 1.0 if n == 1 else (1.0 / max(1, n))
    return {
        "per_agent_fields": per_agent,
        "distinct_field_names": sorted(distinct),
        "alignment": alignment,
    }


async def query_session_metrics(session: str, with_synapse: bool) -> dict:
    """Query Postgres for intent counts + the in-memory bus for envelope counts."""
    if not with_synapse:
        return {"intents": 0, "envelopes_on_stream": 0, "conflicts_detected": 0}
    import asyncpg
    conn = await asyncpg.connect(PG_DSN)
    try:
        rows = await conn.fetch(
            "SELECT agent_id, scope, status FROM intentions WHERE session_id = $1",
            session,
        )
        intents = len(rows)
    finally:
        await conn.close()
    # Read CONFLICT envelopes from the Redis stream + per-agent inboxes.
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        stream_entries = await r.xrange(f"synapse:session:{session}:events", count=100)
        conflict_count = 0
        for _eid, fields in stream_entries:
            try:
                env = json.loads(fields.get("e", "{}"))
                if env.get("type") == "CONFLICT":
                    conflict_count += 1
            except Exception:
                pass
        # Also check per-agent inboxes
        agent_ids = {row["agent_id"] for row in rows}
        for aid in agent_ids:
            inbox = await r.xrange(f"synapse:agent:{aid}:inbox", count=20)
            for _eid, fields in inbox:
                try:
                    env = json.loads(fields.get("e", "{}"))
                    if env.get("type") == "CONFLICT":
                        conflict_count += 1
                except Exception:
                    pass
        await r.close()
    except Exception as e:
        return {"intents": intents, "envelopes_on_stream": -1,
                "conflicts_detected": -1, "redis_err": str(e)[:120]}
    return {"intents": intents, "envelopes_on_stream": len(stream_entries),
            "conflicts_detected": conflict_count}


# ============================================================================
# Prompts (used by every framework)
# ============================================================================
PROMPTS = {
    "architect": ("You are the architect. Write ONE Python class Todo (SQLAlchemy). "
                  "USE FIELD NAME 'description' for the body text. Output ONLY the class, "
                  "4 fields: id, description, completed, created_at. No prose, no fences."),
    "backend":   ("You are the backend engineer. Write ONE Python class Todo (SQLAlchemy). "
                  "USE FIELD NAME 'task' for the body text. Output ONLY the class, "
                  "4 fields: id, task, completed, created_at. No prose, no fences."),
    "tester":    ("You are QA. Write ONE Python class Todo (SQLAlchemy). "
                  "USE FIELD NAME 'content' for the body text. Output ONLY the class, "
                  "4 fields: id, content, completed, created_at. No prose, no fences."),
}


# ============================================================================
# AUTOGEN scenario
# ============================================================================
async def run_autogen(session: str, with_synapse: bool) -> dict:
    import synapse
    if with_synapse:
        os.environ["SYNAPSE_SESSION_ID"] = session
        try:
            synapse.install(framework="autogen", bus_url=REDIS_URL, state_dsn=PG_DSN)
        except Exception:
            pass
    from autogen_agentchat.agents import AssistantAgent
    from autogen_agentchat.messages import TextMessage
    from autogen_core import CancellationToken
    from autogen_core.tools import FunctionTool
    from autogen_ext.models.anthropic import AnthropicChatCompletionClient

    SHARED = f"/tmp/v17_autogen_{('syn' if with_synapse else 'nosyn')}_{session}.py"
    captured: dict[str, str] = {}

    def make_writer(role: str):
        def write_class(class_code: str) -> str:
            captured[role] = class_code
            with open(SHARED, "w") as f:
                f.write(class_code)
            return f"{role} wrote {len(class_code)} bytes"
        write_class.__name__ = f"write_class_{role}"
        return write_class

    client = AnthropicChatCompletionClient(
        model=ANTHROPIC_MODEL,
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        model_info={"vision": False, "function_calling": True,
                    "json_output": False, "family": "claude-haiku-4-5",
                    "structured_output": False},
    )

    async def one(role: str):
        tool = FunctionTool(make_writer(role), description="Write the Todo class.")
        ag = AssistantAgent(
            name=role, model_client=client, tools=[tool],
            system_message=PROMPTS[role] + " Then call write_class_<role> with the class code. Then say DONE.",
        )
        return await ag.on_messages(
            [TextMessage(content="Now produce the Todo class and call your write_class_ tool.", source="user")],
            cancellation_token=CancellationToken(),
        )

    if with_synapse:
        with synapse.with_agent("autogen_orch"):
            await asyncio.gather(one("architect"), one("backend"), one("tester"),
                                 return_exceptions=True)
    else:
        await asyncio.gather(one("architect"), one("backend"), one("tester"),
                             return_exceptions=True)

    outputs = [captured.get("architect", ""), captured.get("backend", ""),
               captured.get("tester", "")]
    out_analysis = analyze_outputs(outputs)
    metrics = await query_session_metrics(session, with_synapse)
    out_analysis.update(metrics)
    out_analysis["shared_path"] = SHARED
    return out_analysis


# ============================================================================
# CREWAI scenario
# ============================================================================
async def run_crewai(session: str, with_synapse: bool) -> dict:
    os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"
    os.environ["OTEL_SDK_DISABLED"] = "true"
    import synapse
    if with_synapse:
        os.environ["SYNAPSE_SESSION_ID"] = session
        try:
            synapse.install(framework="crewai", bus_url=REDIS_URL, state_dsn=PG_DSN)
        except Exception:
            pass
    from crewai import Agent, Task, Crew, Process
    from crewai.tools import tool as crew_tool

    SHARED = f"/tmp/v17_crewai_{('syn' if with_synapse else 'nosyn')}_{session}.py"
    captured: dict[str, str] = {}

    @crew_tool("write_class")
    def write_class(role: str, class_code: str) -> str:
        """Write the Todo class to the shared file."""
        captured[role] = class_code
        with open(SHARED, "w") as f:
            f.write(class_code)
        return f"{role} wrote {len(class_code)} bytes"

    llm = f"anthropic/{ANTHROPIC_MODEL}"
    agents = []
    tasks = []
    for role in ("architect", "backend", "tester"):
        a = Agent(role=role, goal=f"Produce a Todo class with the role's field name",
                 backstory=PROMPTS[role],
                 allow_delegation=False, verbose=False,
                 tools=[write_class], llm=llm)
        agents.append(a)
        tasks.append(Task(
            description=f"As {role}: {PROMPTS[role]} Then call write_class(role={role!r}, class_code=<code>).",
            expected_output="written string", agent=a))
    crew = Crew(agents=agents, tasks=tasks, process=Process.sequential,
                verbose=False, memory=False, cache=False)

    def _run():
        return crew.kickoff()
    await asyncio.wait_for(asyncio.to_thread(_run), timeout=240)

    outputs = [captured.get("architect", ""), captured.get("backend", ""),
               captured.get("tester", "")]
    out_analysis = analyze_outputs(outputs)
    metrics = await query_session_metrics(session, with_synapse)
    out_analysis.update(metrics)
    out_analysis["shared_path"] = SHARED
    return out_analysis


# ============================================================================
# LANGGRAPH scenario
# ============================================================================
async def run_langgraph(session: str, with_synapse: bool) -> dict:
    import synapse
    if with_synapse:
        os.environ["SYNAPSE_SESSION_ID"] = session
        try:
            synapse.install(framework="langgraph", bus_url=REDIS_URL, state_dsn=PG_DSN)
        except Exception:
            pass
    from langchain_anthropic import ChatAnthropic
    from langgraph.prebuilt import create_react_agent
    from langchain_core.tools import tool as lc_tool

    SHARED = f"/tmp/v17_langgraph_{('syn' if with_synapse else 'nosyn')}_{session}.py"
    captured: dict[str, str] = {}

    @lc_tool
    def write_class(role: str, class_code: str) -> str:
        """Write the Todo class to the shared file."""
        captured[role] = class_code
        with open(SHARED, "w") as f:
            f.write(class_code)
        return f"{role} wrote {len(class_code)} bytes"

    llm = ChatAnthropic(model=ANTHROPIC_MODEL, max_tokens=300, temperature=0)
    async def one(role: str):
        agent = create_react_agent(llm, tools=[write_class], name=role)
        return await agent.ainvoke({"messages": [{"role": "user",
            "content": PROMPTS[role] + f" Then call write_class(role={role!r}, class_code=<code>)."}]})
    await asyncio.wait_for(asyncio.gather(one("architect"), one("backend"), one("tester"),
                                          return_exceptions=True), timeout=240)

    outputs = [captured.get("architect", ""), captured.get("backend", ""),
               captured.get("tester", "")]
    out_analysis = analyze_outputs(outputs)
    metrics = await query_session_metrics(session, with_synapse)
    out_analysis.update(metrics)
    out_analysis["shared_path"] = SHARED
    return out_analysis


# ============================================================================
# HERMES scenario (replicates product_dev_hermes pattern)
# ============================================================================
async def run_hermes(session: str, with_synapse: bool) -> dict:
    from synapse.bus import Bus
    from synapse.state import StateGraph
    bus = Bus(REDIS_URL); state = StateGraph(PG_DSN)
    await bus.connect(); await state.connect()
    SHARED = f"/tmp/v17_hermes_{('syn' if with_synapse else 'nosyn')}_{session}.py"
    captured: dict[str, str] = {}

    if with_synapse:
        from synapse.integrations.hermes_integration import (
            install_hermes_synapse_hooks, register_synapse_agent,
            wrap_tool_call_for_synapse, _hermes_runtime,
        )
        _hermes_runtime.clear()
        await install_hermes_synapse_hooks(bus=bus, state=state, session_id=session,
            agent_id="architect", gate_ms=300)
        await register_synapse_agent("backend")
        await register_synapse_agent("tester")

    from anthropic import AsyncAnthropic
    ant = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    async def step(role: str):
        msg = await ant.messages.create(model=ANTHROPIC_MODEL, max_tokens=200,
            messages=[{"role": "user", "content": PROMPTS[role]}])
        text = msg.content[0].text if msg.content else ""
        captured[role] = text

        async def actual_write():
            with open(SHARED, "w") as f:
                f.write(text)
            return f"{role} wrote {len(text)} bytes"

        if with_synapse:
            return await wrap_tool_call_for_synapse(
                "write_file", {"path": SHARED}, actual_write, agent_id=role)
        else:
            return await actual_write()

    try:
        await asyncio.wait_for(asyncio.gather(
            step("architect"), step("backend"), step("tester"),
            return_exceptions=True), timeout=180)
    finally:
        try: await bus.close()
        except Exception: pass
        try: await state.close()
        except Exception: pass

    outputs = [captured.get("architect", ""), captured.get("backend", ""),
               captured.get("tester", "")]
    out_analysis = analyze_outputs(outputs)
    metrics = await query_session_metrics(session, with_synapse)
    out_analysis.update(metrics)
    out_analysis["shared_path"] = SHARED
    return out_analysis


# ============================================================================
# Driver — 4 frameworks × 2 modes = 8 scenarios
# ============================================================================
FRAMEWORKS = [
    ("autogen",   run_autogen),
    ("crewai",    run_crewai),
    ("langgraph", run_langgraph),
    ("hermes",    run_hermes),
]


async def main() -> None:
    import synapse
    print("=== v17 cross-framework value demo (no_synapse vs with_synapse) ===")
    print(f"  synapse v{synapse.__version__}")
    print(f"  primary LLM: {ANTHROPIC_MODEL}")
    await apply_migrations()

    summary: dict[str, dict] = {}
    for fw, fn in FRAMEWORKS:
        print(f"\n=========== {fw} ===========")
        # mode 1: no_synapse
        sess_no = f"v17_{fw}_nosyn_{int(time.time())}"
        try:
            print(f"--- {fw} no_synapse ---")
            no_syn = await asyncio.wait_for(fn(sess_no, False), timeout=300)
        except Exception as e:
            no_syn = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
            print(f"  ERROR: {no_syn['error']}")
        print(f"  distinct={no_syn.get('distinct_field_names')} "
              f"alignment={no_syn.get('alignment', 0.0):.2f} "
              f"intents={no_syn.get('intents', 0)} "
              f"conflicts={no_syn.get('conflicts_detected', 0)} "
              f"envelopes={no_syn.get('envelopes_on_stream', 0)}")

        # Quick pause so Postgres rows from no_synapse don't interleave with with_synapse
        await asyncio.sleep(1.0)

        sess_yes = f"v17_{fw}_syn_{int(time.time())}"
        try:
            print(f"--- {fw} with_synapse ---")
            with_syn = await asyncio.wait_for(fn(sess_yes, True), timeout=300)
        except Exception as e:
            with_syn = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
            print(f"  ERROR: {with_syn['error']}")
        print(f"  distinct={with_syn.get('distinct_field_names')} "
              f"alignment={with_syn.get('alignment', 0.0):.2f} "
              f"intents={with_syn.get('intents', 0)} "
              f"conflicts={with_syn.get('conflicts_detected', 0)} "
              f"envelopes={with_syn.get('envelopes_on_stream', 0)}")

        summary[fw] = {"no_synapse": no_syn, "with_synapse": with_syn}

    print("\n" + "=" * 100)
    print("  v17 CROSS-FRAMEWORK VALUE DEMO SUMMARY")
    print("=" * 100)
    print(f"  {'framework':<12} {'mode':<14} {'distinct':<25} {'align':<6} {'intents':<8} {'conflicts':<10} {'envelopes':<10}")
    for fw, _ in FRAMEWORKS:
        for mode in ("no_synapse", "with_synapse"):
            d = summary[fw][mode]
            print(f"  {fw:<12} {mode:<14} {str(d.get('distinct_field_names', '?')):<25} "
                  f"{d.get('alignment', 0.0):<6.2f} "
                  f"{str(d.get('intents', 0)):<8} "
                  f"{str(d.get('conflicts_detected', 0)):<10} "
                  f"{str(d.get('envelopes_on_stream', 0)):<10}")

    out = f"/tmp/public_benchmark_v17_{int(time.time())}.json"
    with open(out, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
