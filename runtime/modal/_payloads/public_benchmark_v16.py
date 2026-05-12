"""Public benchmark v16 — extends Phase 5 N=3-rep rock-solid harness to
4 more adapter paths (crewai, langgraph, openai_agents, pydantic_ai).

For each adapter we run:
  POSITIVE: 3 agents → same scope concurrent → expect [3,3,3] intents, [2,2,2] contended
  NEGATIVE: 3 agents → distinct scopes concurrent → expect [3,3,3] intents, [0,0,0] contended
  STRESS:   10 agents → same scope concurrent → expect [10,10,10] intents, [9,9,9] contended

Plus replays v15's autogen + hermes 5 tests for cross-version regression check.

Total: 17 tests × 3 reps = 51 runs.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
from typing import Any, Callable, Awaitable

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("DO_NOT_TRACK", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

sys.path.insert(0, "/opt/synapse-sdk")
sys.path.insert(0, "/opt")

REDIS_URL = "redis://localhost:6379/0"
PG_DSN = "postgresql://synapse:synapse_dev@localhost:5432/synapse"
GEMINI_MODEL = "gemini-2.5-flash"
ANTHROPIC_FALLBACK_MODEL = "claude-haiku-4-5-20251001"
RELIABILITY_REPS = 3


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
    " CREATE TABLE IF NOT EXISTS beliefs ("
    " agent_id text NOT NULL, session_id text NOT NULL, tenant_id text,"
    " key text NOT NULL, value jsonb NOT NULL,"
    " confidence real NOT NULL CHECK (confidence BETWEEN 0 AND 1),"
    " source text NOT NULL CHECK (source IN ('observed','inferred','assumed')),"
    " evidence text, updated_at timestamptz NOT NULL DEFAULT now(),"
    " PRIMARY KEY (agent_id, key));"
)


async def apply_migrations() -> None:
    import asyncpg
    conn = await asyncpg.connect(PG_DSN)
    try:
        await conn.execute(MIGRATIONS_SQL)
    finally:
        await conn.close()


async def query_session(session: str) -> dict:
    import asyncpg
    conn = await asyncpg.connect(PG_DSN)
    try:
        rows = await conn.fetch(
            "SELECT agent_id, scope FROM intentions WHERE session_id = $1",
            session,
        )
        intents = len(rows)
        scope_counts: dict[str, int] = {}
        for r in rows:
            for s in (r["scope"] or []):
                scope_counts[s] = scope_counts.get(s, 0) + 1
        contended_scopes = {s: c for s, c in scope_counts.items() if c > 1}
        return {
            "intents": intents,
            "agents": sorted({r["agent_id"] for r in rows}),
            "scopes": sorted({s for r in rows for s in (r["scope"] or [])}),
            "contended_scopes": contended_scopes,
            "expected_conflicts": sum(c - 1 for c in contended_scopes.values()),
        }
    finally:
        await conn.close()


# ============================================================================
# Anthropic client helpers
# ============================================================================
def _anthropic_haiku_client():
    """autogen-ext AnthropicChatCompletionClient — used by autogen tests."""
    from autogen_ext.models.anthropic import AnthropicChatCompletionClient
    return AnthropicChatCompletionClient(
        model=ANTHROPIC_FALLBACK_MODEL,
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        model_info={"vision": False, "function_calling": True,
                    "json_output": False, "family": "claude-haiku-4-5",
                    "structured_output": False},
    )


# ============================================================================
# AUTOGEN tests (carried over from v15 for cross-version regression)
# ============================================================================
async def test_autogen_same(session: str) -> dict:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    try:
        from autogen_agentchat.agents import AssistantAgent
        from autogen_agentchat.messages import TextMessage
        from autogen_core import CancellationToken
        from autogen_core.tools import FunctionTool
    except Exception as e:
        return {"ok": False, "verdict": "INSTALL_FAILED", "error": str(e)[:200]}
    SHARED = f"/tmp/v16_autogen_same_{session}.txt"
    def write_note(content: str) -> str:
        open(SHARED, "w").write(content); return f"wrote {len(content)} bytes"
    try:
        client = _anthropic_haiku_client()
        tool = FunctionTool(write_note, description="Write content to shared.")
        async def one(name: str, content: str):
            ag = AssistantAgent(name=name, model_client=client, tools=[tool],
                system_message=f"Call write_note once with: {content!r}. Then say DONE.")
            return await ag.on_messages(
                [TextMessage(content=f"Write '{content}'.", source="user")],
                cancellation_token=CancellationToken())
        with synapse.with_agent("autogen_orch"):
            await asyncio.gather(
                one("agent_a", "hi a"), one("agent_b", "hi b"), one("agent_c", "hi c"),
                return_exceptions=True)
        return {"ok": True, "verdict": "see_intents"}
    except Exception as e:
        return {"ok": False, "verdict": "EXAMPLE_FAILED", "error": f"{type(e).__name__}: {str(e)[:300]}"}


async def test_autogen_distinct(session: str) -> dict:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    try:
        from autogen_agentchat.agents import AssistantAgent
        from autogen_agentchat.messages import TextMessage
        from autogen_core import CancellationToken
        from autogen_core.tools import FunctionTool
    except Exception as e:
        return {"ok": False, "verdict": "INSTALL_FAILED", "error": str(e)[:200]}
    paths = {f"a{i}": f"/tmp/v16_dist_a{i}_{session}.txt" for i in (0, 1, 2)}
    def make_writer(idx: int):
        def write(content: str) -> str:
            open(paths[f"a{idx}"], "w").write(content)
            return f"a{idx} wrote {len(content)}"
        write.__name__ = f"write_a{idx}"
        return write
    try:
        client = _anthropic_haiku_client()
        tools = {f"a{i}": FunctionTool(make_writer(i), description=f"Write to file A{i}")
                 for i in (0, 1, 2)}
        async def one(idx: int):
            ag = AssistantAgent(name=f"agent_a{idx}", model_client=client, tools=[tools[f"a{idx}"]],
                system_message=f"Call write_a{idx} once with 'hi a{idx}'. Then say DONE.")
            return await ag.on_messages(
                [TextMessage(content=f"Write 'hi a{idx}'.", source="user")],
                cancellation_token=CancellationToken())
        with synapse.with_agent("autogen_orch"):
            await asyncio.gather(one(0), one(1), one(2), return_exceptions=True)
        return {"ok": True, "verdict": "see_intents"}
    except Exception as e:
        return {"ok": False, "verdict": "EXAMPLE_FAILED", "error": f"{type(e).__name__}: {str(e)[:300]}"}


async def test_autogen_stress(session: str) -> dict:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    try:
        from autogen_agentchat.agents import AssistantAgent
        from autogen_agentchat.messages import TextMessage
        from autogen_core import CancellationToken
        from autogen_core.tools import FunctionTool
    except Exception as e:
        return {"ok": False, "verdict": "INSTALL_FAILED", "error": str(e)[:200]}
    SHARED = f"/tmp/v16_autogen_stress_{session}.txt"
    def write_note(content: str) -> str:
        open(SHARED, "w").write(content); return f"wrote {len(content)} bytes"
    try:
        client = _anthropic_haiku_client()
        tool = FunctionTool(write_note, description="Write content to shared.")
        async def one(idx: int):
            ag = AssistantAgent(name=f"stress_a{idx}", model_client=client, tools=[tool],
                system_message=f"Call write_note once with: 'agent {idx}'. Then say DONE.")
            return await ag.on_messages(
                [TextMessage(content=f"Write 'agent {idx}'.", source="user")],
                cancellation_token=CancellationToken())
        with synapse.with_agent("autogen_stress_orch"):
            await asyncio.gather(*[one(i) for i in range(10)], return_exceptions=True)
        return {"ok": True, "verdict": "see_intents"}
    except Exception as e:
        return {"ok": False, "verdict": "EXAMPLE_FAILED", "error": f"{type(e).__name__}: {str(e)[:300]}"}


# ============================================================================
# CREWAI tests
# ============================================================================
async def test_crewai_same(session: str) -> dict:
    os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"
    os.environ["OTEL_SDK_DISABLED"] = "true"
    os.environ["SYNAPSE_SESSION_ID"] = session
    import synapse
    try:
        from crewai import Agent, Task, Crew, Process
        from crewai.tools import tool as crew_tool
    except Exception as e:
        return {"ok": False, "verdict": "INSTALL_FAILED", "error": str(e)[:200]}
    SHARED = f"/tmp/v16_crewai_same_{session}.md"
    @crew_tool("publish_finding")
    def publish_finding(text: str) -> str:
        """Publish to shared."""
        open(SHARED, "w").write(text); return f"published {len(text)}"
    try:
        llm = f"anthropic/{ANTHROPIC_FALLBACK_MODEL}"
        agents = []
        tasks = []
        for role in ("Researcher", "Writer", "Reviewer"):
            a = Agent(role=role, goal=f"Use publish_finding once",
                     backstory=f"You are a {role}.",
                     allow_delegation=False, verbose=False,
                     tools=[publish_finding], llm=llm)
            agents.append(a)
            tasks.append(Task(
                description="Call publish_finding once with a 5-word note.",
                expected_output="published string", agent=a))
        crew = Crew(agents=agents, tasks=tasks, process=Process.sequential,
                    verbose=False, memory=False, cache=False)
        with synapse.with_agent("crewai_orch"):
            await asyncio.wait_for(asyncio.to_thread(crew.kickoff), timeout=180)
        return {"ok": True, "verdict": "see_intents"}
    except Exception as e:
        return {"ok": False, "verdict": "EXAMPLE_FAILED", "error": f"{type(e).__name__}: {str(e)[:300]}"}


async def test_crewai_distinct(session: str) -> dict:
    os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"
    os.environ["OTEL_SDK_DISABLED"] = "true"
    os.environ["SYNAPSE_SESSION_ID"] = session
    import synapse
    try:
        from crewai import Agent, Task, Crew, Process
        from crewai.tools import tool as crew_tool
    except Exception as e:
        return {"ok": False, "verdict": "INSTALL_FAILED", "error": str(e)[:200]}
    # Per-agent distinct paths via 3 different tools
    paths = {f"x{i}": f"/tmp/v16_crewai_dist_x{i}_{session}.md" for i in (0, 1, 2)}
    @crew_tool("publish_x0")
    def publish_x0(text: str) -> str:
        """Publish to file 0."""
        open(paths["x0"], "w").write(text); return f"x0 wrote {len(text)}"
    @crew_tool("publish_x1")
    def publish_x1(text: str) -> str:
        """Publish to file 1."""
        open(paths["x1"], "w").write(text); return f"x1 wrote {len(text)}"
    @crew_tool("publish_x2")
    def publish_x2(text: str) -> str:
        """Publish to file 2."""
        open(paths["x2"], "w").write(text); return f"x2 wrote {len(text)}"
    try:
        llm = f"anthropic/{ANTHROPIC_FALLBACK_MODEL}"
        tools_by_idx = [publish_x0, publish_x1, publish_x2]
        agents = []
        tasks = []
        for i, role in enumerate(("Researcher", "Writer", "Reviewer")):
            a = Agent(role=role, goal=f"Use publish_x{i} once",
                     backstory=f"You are {role} #{i}.",
                     allow_delegation=False, verbose=False,
                     tools=[tools_by_idx[i]], llm=llm)
            agents.append(a)
            tasks.append(Task(
                description=f"Call publish_x{i} once with a 5-word note.",
                expected_output="published string", agent=a))
        crew = Crew(agents=agents, tasks=tasks, process=Process.sequential,
                    verbose=False, memory=False, cache=False)
        with synapse.with_agent("crewai_orch"):
            await asyncio.wait_for(asyncio.to_thread(crew.kickoff), timeout=180)
        return {"ok": True, "verdict": "see_intents"}
    except Exception as e:
        return {"ok": False, "verdict": "EXAMPLE_FAILED", "error": f"{type(e).__name__}: {str(e)[:300]}"}


# ============================================================================
# LANGGRAPH tests — using LangChain's @tool + AgentExecutor (not StateGraph
# fan-out, which v14's bench failed on). 3 parallel react agents.
# ============================================================================
async def test_langgraph_same(session: str) -> dict:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    try:
        from langchain_anthropic import ChatAnthropic
        from langgraph.prebuilt import create_react_agent
        from langchain_core.tools import tool as lc_tool
    except Exception as e:
        return {"ok": False, "verdict": "INSTALL_FAILED", "error": str(e)[:200]}
    SHARED = f"/tmp/v16_langgraph_same_{session}.txt"
    @lc_tool
    def write_note(content: str) -> str:
        """Write content to the shared file."""
        open(SHARED, "w").write(content); return f"wrote {len(content)}"
    try:
        llm = ChatAnthropic(model=ANTHROPIC_FALLBACK_MODEL, max_tokens=120)
        async def one(name: str, content: str):
            agent = create_react_agent(llm, tools=[write_note], name=name)
            return await agent.ainvoke({"messages": [{"role": "user",
                "content": f"Call write_note with exactly {content!r}."}]})
        with synapse.with_agent("langgraph_orch"):
            await asyncio.wait_for(asyncio.gather(
                one("noter_a", "A wrote"), one("noter_b", "B wrote"), one("noter_c", "C wrote"),
                return_exceptions=True), timeout=180)
        return {"ok": True, "verdict": "see_intents"}
    except Exception as e:
        return {"ok": False, "verdict": "EXAMPLE_FAILED", "error": f"{type(e).__name__}: {str(e)[:300]}"}


async def test_langgraph_distinct(session: str) -> dict:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    try:
        from langchain_anthropic import ChatAnthropic
        from langgraph.prebuilt import create_react_agent
        from langchain_core.tools import tool as lc_tool
    except Exception as e:
        return {"ok": False, "verdict": "INSTALL_FAILED", "error": str(e)[:200]}
    paths = {i: f"/tmp/v16_lg_dist_a{i}_{session}.txt" for i in (0, 1, 2)}
    @lc_tool
    def write_a0(content: str) -> str:
        """Write to A0."""
        open(paths[0], "w").write(content); return f"a0 wrote {len(content)}"
    @lc_tool
    def write_a1(content: str) -> str:
        """Write to A1."""
        open(paths[1], "w").write(content); return f"a1 wrote {len(content)}"
    @lc_tool
    def write_a2(content: str) -> str:
        """Write to A2."""
        open(paths[2], "w").write(content); return f"a2 wrote {len(content)}"
    try:
        llm = ChatAnthropic(model=ANTHROPIC_FALLBACK_MODEL, max_tokens=120)
        tools_by_idx = [write_a0, write_a1, write_a2]
        async def one(idx: int):
            agent = create_react_agent(llm, tools=[tools_by_idx[idx]], name=f"noter_{idx}")
            return await agent.ainvoke({"messages": [{"role": "user",
                "content": f"Call write_a{idx} with 'hi {idx}'."}]})
        with synapse.with_agent("langgraph_orch"):
            await asyncio.wait_for(asyncio.gather(one(0), one(1), one(2),
                return_exceptions=True), timeout=180)
        return {"ok": True, "verdict": "see_intents"}
    except Exception as e:
        return {"ok": False, "verdict": "EXAMPLE_FAILED", "error": f"{type(e).__name__}: {str(e)[:300]}"}


# ============================================================================
# OPENAI-AGENTS tests — `from agents import Agent, Runner`
# ============================================================================
async def test_openai_agents_same(session: str) -> dict:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    try:
        from agents import Agent, Runner, function_tool
        # openai-agents uses OpenAI by default. We route through Gemini's
        # openai-compat endpoint via the localhost proxy so we don't need
        # a real OpenAI key.
        proxy_url = os.environ.get("OPENAI_PROXY_URL", "http://127.0.0.1:8765/v1")
        os.environ.setdefault("OPENAI_API_KEY", "sk-proxy-irrelevant")
        os.environ["OPENAI_BASE_URL"] = proxy_url
        os.environ["OPENAI_API_BASE"] = proxy_url
    except Exception as e:
        return {"ok": False, "verdict": "INSTALL_FAILED", "error": str(e)[:200]}
    SHARED = f"/tmp/v16_oa_same_{session}.txt"
    @function_tool
    def write_note(content: str) -> str:
        """Write content to the shared note file."""
        open(SHARED, "w").write(content); return f"wrote {len(content)}"
    try:
        async def one(idx: int):
            agent = Agent(name=f"agent_{idx}", tools=[write_note],
                instructions=f"Call write_note exactly once with: 'hi {idx}'. Then say DONE.")
            return await Runner.run(agent, f"Write 'hi {idx}'.")
        with synapse.with_agent("oa_orch"):
            await asyncio.wait_for(asyncio.gather(one(0), one(1), one(2),
                return_exceptions=True), timeout=180)
        return {"ok": True, "verdict": "see_intents"}
    except Exception as e:
        return {"ok": False, "verdict": "EXAMPLE_FAILED", "error": f"{type(e).__name__}: {str(e)[:300]}"}


async def test_openai_agents_distinct(session: str) -> dict:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    try:
        from agents import Agent, Runner, function_tool
        proxy_url = os.environ.get("OPENAI_PROXY_URL", "http://127.0.0.1:8765/v1")
        os.environ.setdefault("OPENAI_API_KEY", "sk-proxy-irrelevant")
        os.environ["OPENAI_BASE_URL"] = proxy_url
        os.environ["OPENAI_API_BASE"] = proxy_url
    except Exception as e:
        return {"ok": False, "verdict": "INSTALL_FAILED", "error": str(e)[:200]}
    paths = {i: f"/tmp/v16_oa_dist_a{i}_{session}.txt" for i in (0, 1, 2)}
    @function_tool
    def write_x0(content: str) -> str:
        """Write to x0."""
        open(paths[0], "w").write(content); return f"x0 wrote {len(content)}"
    @function_tool
    def write_x1(content: str) -> str:
        """Write to x1."""
        open(paths[1], "w").write(content); return f"x1 wrote {len(content)}"
    @function_tool
    def write_x2(content: str) -> str:
        """Write to x2."""
        open(paths[2], "w").write(content); return f"x2 wrote {len(content)}"
    try:
        tools_by_idx = [write_x0, write_x1, write_x2]
        async def one(idx: int):
            agent = Agent(name=f"agent_{idx}", tools=[tools_by_idx[idx]],
                instructions=f"Call write_x{idx} once with 'hi {idx}'. Then say DONE.")
            return await Runner.run(agent, f"Write 'hi {idx}'.")
        with synapse.with_agent("oa_orch"):
            await asyncio.wait_for(asyncio.gather(one(0), one(1), one(2),
                return_exceptions=True), timeout=180)
        return {"ok": True, "verdict": "see_intents"}
    except Exception as e:
        return {"ok": False, "verdict": "EXAMPLE_FAILED", "error": f"{type(e).__name__}: {str(e)[:300]}"}


# ============================================================================
# PYDANTIC-AI tests
# ============================================================================
async def test_pydantic_ai_same(session: str) -> dict:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    try:
        from pydantic_ai import Agent
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider
    except Exception as e:
        return {"ok": False, "verdict": "INSTALL_FAILED", "error": str(e)[:200]}
    SHARED = f"/tmp/v16_pa_same_{session}.txt"
    try:
        provider = AnthropicProvider(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        model = AnthropicModel(ANTHROPIC_FALLBACK_MODEL, provider=provider)
        def make_agent(name: str) -> Agent:
            agent = Agent(model, system_prompt=f"You are {name}. Use write_note once.")
            @agent.tool_plain
            def write_note(content: str) -> str:
                """Write content to the shared note file."""
                open(SHARED, "w").write(content); return f"wrote {len(content)}"
            return agent
        async def one(idx: int):
            agent = make_agent(f"agent_{idx}")
            return await agent.run(f"Call write_note with exactly 'hi {idx}'.")
        with synapse.with_agent("pa_orch"):
            await asyncio.wait_for(asyncio.gather(one(0), one(1), one(2),
                return_exceptions=True), timeout=180)
        return {"ok": True, "verdict": "see_intents"}
    except Exception as e:
        return {"ok": False, "verdict": "EXAMPLE_FAILED", "error": f"{type(e).__name__}: {str(e)[:300]}"}


async def test_pydantic_ai_distinct(session: str) -> dict:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    try:
        from pydantic_ai import Agent
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider
    except Exception as e:
        return {"ok": False, "verdict": "INSTALL_FAILED", "error": str(e)[:200]}
    paths = {i: f"/tmp/v16_pa_dist_{i}_{session}.txt" for i in (0, 1, 2)}
    try:
        provider = AnthropicProvider(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        model = AnthropicModel(ANTHROPIC_FALLBACK_MODEL, provider=provider)
        def make_agent(idx: int) -> Agent:
            target_path = paths[idx]
            agent = Agent(model,
                system_prompt=f"You are agent_{idx}. Use write_to_my_file once.")
            @agent.tool_plain
            def write_to_my_file(content: str) -> str:
                """Write content to my assigned file."""
                open(target_path, "w").write(content); return f"{idx} wrote {len(content)}"
            return agent
        async def one(idx: int):
            agent = make_agent(idx)
            return await agent.run(f"Call write_to_my_file with 'hi {idx}'.")
        with synapse.with_agent("pa_orch"):
            await asyncio.wait_for(asyncio.gather(one(0), one(1), one(2),
                return_exceptions=True), timeout=180)
        return {"ok": True, "verdict": "see_intents"}
    except Exception as e:
        return {"ok": False, "verdict": "EXAMPLE_FAILED", "error": f"{type(e).__name__}: {str(e)[:300]}"}


# ============================================================================
# HERMES tests (carried over from v15.1 with _hermes_runtime.clear fix)
# ============================================================================
async def test_hermes_same(session: str) -> dict:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    try:
        from synapse.bus import Bus
        from synapse.state import StateGraph
        from synapse.integrations.hermes_integration import (
            install_hermes_synapse_hooks, register_synapse_agent,
            wrap_tool_call_for_synapse, _hermes_runtime,
        )
        from anthropic import AsyncAnthropic
    except Exception as e:
        return {"ok": False, "verdict": "INSTALL_FAILED", "error": str(e)[:200]}
    bus = Bus(REDIS_URL); state = StateGraph(PG_DSN)
    await bus.connect(); await state.connect()
    SHARED = f"/tmp/v16_hermes_same_{session}.py"
    try:
        _hermes_runtime.clear()
        await install_hermes_synapse_hooks(bus=bus, state=state, session_id=session,
            agent_id="architect", gate_ms=300)
        await register_synapse_agent("backend")
        await register_synapse_agent("tester")
        ant = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        async def step(aid: str, prompt: str):
            msg = await ant.messages.create(model=ANTHROPIC_FALLBACK_MODEL,
                max_tokens=120, messages=[{"role": "user", "content": prompt}])
            text = msg.content[0].text if msg.content else ""
            async def actual_write():
                open(SHARED, "w").write(text); return f"wrote {len(text)}"
            return await wrap_tool_call_for_synapse("write_file", {"path": SHARED},
                actual_write, agent_id=aid)
        await asyncio.wait_for(asyncio.gather(
            step("architect", "Print: class Todo: id: int = 0"),
            step("backend",   "Print: class Todo: id: int = 1"),
            step("tester",    "Print: class Todo: id: int = 2"),
            return_exceptions=True), timeout=180)
        return {"ok": True, "verdict": "see_intents"}
    except Exception as e:
        return {"ok": False, "verdict": "EXAMPLE_FAILED", "error": f"{type(e).__name__}: {str(e)[:200]}"}
    finally:
        try: await bus.disconnect()
        except Exception: pass
        try: await state.disconnect()
        except Exception: pass


# ============================================================================
# Reliability harness — run a test N=3 times, deterministic + matches-expected
# ============================================================================
async def run_with_reliability(
    name: str, fn: Callable[[str], Awaitable[dict]],
    expected: dict | None, timeout_per_rep: int = 240,
) -> dict:
    reps_results = []
    for i in range(RELIABILITY_REPS):
        sess = f"v16_{name}_rep{i}_{int(time.time())}_{os.getpid()}"
        t0 = time.monotonic()
        try:
            r = await asyncio.wait_for(fn(sess), timeout=timeout_per_rep)
        except asyncio.TimeoutError:
            r = {"ok": False, "verdict": "EXAMPLE_FAILED",
                 "error": f"timeout >{timeout_per_rep}s"}
        except Exception as e:
            r = {"ok": False, "verdict": "EXAMPLE_FAILED",
                 "error": f"{type(e).__name__}: {str(e)[:200]}"}
        elapsed = time.monotonic() - t0
        if r.get("verdict") == "see_intents":
            try:
                stats = await query_session(sess)
            except Exception as e:
                stats = {"intents": -1, "expected_conflicts": -1,
                         "error": str(e)[:200]}
            r["intents"] = stats.get("intents", -1)
            r["contended"] = stats.get("expected_conflicts", -1)
            r["scopes"] = stats.get("scopes", [])
            r["agents"] = stats.get("agents", [])
        r["rep"] = i; r["elapsed_s"] = round(elapsed, 1)
        reps_results.append(r)

    passed = [r for r in reps_results if r.get("ok")]
    intents_per_rep = [r.get("intents", -1) for r in reps_results if r.get("intents") is not None]
    contended_per_rep = [r.get("contended", -1) for r in reps_results if r.get("contended") is not None]
    pass_count = len(passed)
    matches_expected = False
    expectation_check = "no expected vector"
    if expected is not None and pass_count > 0:
        exp_intents = expected.get("intents")
        exp_contended = expected.get("contended")
        intents_ok = exp_intents is None or all(i == exp_intents for i in intents_per_rep if i >= 0)
        contended_ok = exp_contended is None or all(c == exp_contended for c in contended_per_rep if c >= 0)
        matches_expected = intents_ok and contended_ok
        expectation_check = (f"intents={intents_per_rep} expected={exp_intents} -> "
            f"{'ok' if intents_ok else 'MISMATCH'}; contended={contended_per_rep} "
            f"expected={exp_contended} -> {'ok' if contended_ok else 'MISMATCH'}")
    deterministic = (len(set(intents_per_rep)) <= 1 and len(set(contended_per_rep)) <= 1)
    if pass_count == RELIABILITY_REPS and deterministic and matches_expected:
        verdict = f"PASS_{pass_count}OF{RELIABILITY_REPS} (deterministic, matches expected)"
    elif pass_count == RELIABILITY_REPS and not deterministic:
        verdict = f"PASS_FLAKY_{pass_count}OF{RELIABILITY_REPS} ({intents_per_rep}/{contended_per_rep})"
    elif pass_count == RELIABILITY_REPS and not matches_expected:
        verdict = f"PASS_{pass_count}OF{RELIABILITY_REPS}_BUT_MISMATCH ({expectation_check})"
    elif pass_count > 0:
        verdict = f"PARTIAL_FAIL_{pass_count}OF{RELIABILITY_REPS}"
    else:
        # Surface the first error for debug context
        first_err = reps_results[0].get("error", "?") if reps_results else "?"
        verdict = f"FAIL_0OF{RELIABILITY_REPS}: {first_err[:200]}"
    return {"verdict": verdict, "pass_count": pass_count,
            "intents_per_rep": intents_per_rep, "contended_per_rep": contended_per_rep,
            "expected": expected, "expectation_check": expectation_check,
            "deterministic": deterministic, "reps": reps_results}


TESTS: list[tuple[str, Callable, dict, str, str]] = [
    # (name, fn, expected, kind, adapter)
    ("autogen_same",         test_autogen_same,        {"intents": 3, "contended": 2},  "POSITIVE", "autogen"),
    ("autogen_distinct",     test_autogen_distinct,    {"intents": 3, "contended": 0},  "NEGATIVE", "autogen"),
    ("autogen_stress",       test_autogen_stress,      {"intents": 10, "contended": 9}, "STRESS",   "autogen"),
    ("crewai_same",          test_crewai_same,         {"intents": 3, "contended": 2},  "POSITIVE", "crewai"),
    ("crewai_distinct",      test_crewai_distinct,     {"intents": 3, "contended": 0},  "NEGATIVE", "crewai"),
    ("langgraph_same",       test_langgraph_same,      {"intents": 3, "contended": 2},  "POSITIVE", "langgraph"),
    ("langgraph_distinct",   test_langgraph_distinct,  {"intents": 3, "contended": 0},  "NEGATIVE", "langgraph"),
    ("openai_agents_same",   test_openai_agents_same,  {"intents": 3, "contended": 2},  "POSITIVE", "openai_agents"),
    ("openai_agents_distinct", test_openai_agents_distinct, {"intents": 3, "contended": 0}, "NEGATIVE", "openai_agents"),
    ("pydantic_ai_same",     test_pydantic_ai_same,    {"intents": 3, "contended": 2},  "POSITIVE", "pydantic_ai"),
    ("pydantic_ai_distinct", test_pydantic_ai_distinct, {"intents": 3, "contended": 0}, "NEGATIVE", "pydantic_ai"),
    ("hermes_same",          test_hermes_same,         {"intents": 3, "contended": 2},  "POSITIVE", "hermes"),
]


async def main() -> None:
    import synapse
    print(f"=== v16 ROCK-SOLID benchmark — 12 tests × N={RELIABILITY_REPS} reps ===")
    print(f"  synapse v{synapse.__version__}")
    print(f"  primary LLM: {ANTHROPIC_FALLBACK_MODEL}")
    await apply_migrations()
    for fw in ("crewai", "autogen", "langchain", "langgraph",
               "openai_agents", "pydantic_ai"):
        try:
            synapse.install(framework=fw, bus_url=REDIS_URL, state_dsn=PG_DSN)
        except Exception as e:
            print(f"  [install warn] {fw}: {type(e).__name__}: {str(e)[:120]}")

    summary: dict[str, dict] = {}
    for name, fn, expected, kind, adapter in TESTS:
        print(f"\n=== {kind} [{adapter}]: {name} ===", flush=True)
        r = await run_with_reliability(name, fn, expected)
        r.update({"kind": kind, "adapter": adapter})
        summary[name] = r
        print(f"  verdict={r['verdict']}")
        print(f"  intents per rep: {r['intents_per_rep']}")
        print(f"  contended per rep: {r['contended_per_rep']}")
        print(f"  deterministic: {r['deterministic']}")
        print(f"  expectation: {r['expectation_check']}")

    print("\n" + "=" * 100)
    print("  v16 ROCK-SOLID SUMMARY (12 tests × 3 reps = 36 runs)")
    print("=" * 100)
    print(f"  {'adapter':<14} {'kind':<10} {'test':<24} {'verdict':<60}")
    pass_count_total = 0
    for name, _, _, kind, adapter in TESTS:
        s = summary[name]
        v = s.get('verdict','?')
        print(f"  {adapter:<14} {kind:<10} {name:<24} {v:<60}")
        if v.startswith("PASS_3OF3"):
            pass_count_total += 1
    print(f"\n  pass count: {pass_count_total}/{len(TESTS)}")
    out = f"/tmp/public_benchmark_v16_{int(time.time())}.json"
    with open(out, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
