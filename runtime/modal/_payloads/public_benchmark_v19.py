"""Public benchmark v19 — END-TO-END V1 PRODUCT BUILDS across all adapters.

Each test:
  1. Installs the framework adapter via synapse.install(framework=...)
  2. Asks the LLM (via the framework's canonical API) to PRODUCE a fizzbuzz
     Python function and call a write_code(content=...) tool with it.
  3. Captures the generated code from the tool call (or the LLM response if
     the framework didn't make a tool call).
  4. EXECUTES the generated file and asserts:
       fizzbuzz(15)=="FizzBuzz", fizzbuzz(3)=="Fizz",
       fizzbuzz(10)=="Buzz", fizzbuzz(1)=="1"
  5. Reports V1_PASS (artifact runs + correct output) or V1_FAILED
     (artifact crashes or wrong output).

This is the rock-solid "Synapse + framework actually produces working
software" benchmark.

Adapters tested (10 Python — Node openclaw runs separately):
  autogen, crewai, langgraph, hermes, smolagents, agno, llama_index,
  pydantic_ai, openai_agents, google_adk

Cost target: ~$5 LLM total (10 adapters × ~$0.50 each at Haiku 4.5).
Wall: ~20-40 minutes.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Awaitable

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("DO_NOT_TRACK", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

sys.path.insert(0, "/opt/synapse-sdk")
sys.path.insert(0, "/opt")

REDIS_URL = "redis://localhost:6379/0"
PG_DSN = "postgresql://synapse:synapse_dev@localhost:5432/synapse"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
GEMINI_MODEL = "gemini-2.5-flash"


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
    try: await conn.execute(MIGRATIONS_SQL)
    finally: await conn.close()


async def query_session_intents(session: str) -> dict:
    import asyncpg
    conn = await asyncpg.connect(PG_DSN)
    try:
        rows = await conn.fetch(
            "SELECT agent_id, scope FROM intentions WHERE session_id = $1",
            session,
        )
        return {"intents": len(rows),
                "agents": sorted({r["agent_id"] for r in rows})}
    finally: await conn.close()


# ============================================================================
# V1 spec — the bar an adapter must clear
# ============================================================================
FIZZBUZZ_PROMPT = (
    "Write a Python function called `fizzbuzz(n: int) -> str` that returns:\n"
    "  - 'FizzBuzz' if n is divisible by both 3 AND 5\n"
    "  - 'Fizz' if n is divisible by 3 only\n"
    "  - 'Buzz' if n is divisible by 5 only\n"
    "  - str(n) otherwise\n"
    "Call the write_code tool with the FULL function definition (def line + body). "
    "Output ONLY the function — no imports, no comments, no markdown fences, no prose. "
    "Then say DONE."
)

# Validation asserts run on the produced code
V1_ASSERTIONS = [
    (15, "FizzBuzz"),
    (9, "Fizz"),
    (10, "Buzz"),
    (1, "1"),
    (0, "FizzBuzz"),  # 0 is divisible by both, edge case
    (-3, "Fizz"),
]


def execute_and_verify(code: str) -> tuple[bool, str]:
    """Execute code as a Python module, call fizzbuzz, assert outputs.
    Returns (passed, reason)."""
    # Strip common LLM-output artifacts
    code = code.strip()
    if code.startswith("```"):
        # Strip code fence
        lines = code.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        code = "\n".join(lines)
    # Extract function definition if there's prose before it
    m = re.search(r"(def\s+fizzbuzz\s*\([^)]*\)\s*(?:->[^:]+)?\s*:.*?)(?=\n(?:def |class |\Z))",
                  code, re.DOTALL)
    if m:
        code = m.group(1)

    # Try to exec it
    try:
        namespace: dict[str, Any] = {}
        exec(code, namespace)
        fn = namespace.get("fizzbuzz")
        if not callable(fn):
            return False, f"fizzbuzz not defined; code length={len(code)}"
        for n, expected in V1_ASSERTIONS:
            got = fn(n)
            if str(got) != expected:
                return False, f"fizzbuzz({n}) returned {got!r}, expected {expected!r}"
        return True, "all assertions passed"
    except Exception as e:
        return False, f"exec failed: {type(e).__name__}: {str(e)[:200]}"


# ============================================================================
# Per-adapter end-to-end V1 builders
# ============================================================================
async def build_autogen(session: str) -> dict:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    try:
        from autogen_agentchat.agents import AssistantAgent
        from autogen_agentchat.messages import TextMessage
        from autogen_core import CancellationToken
        from autogen_core.tools import FunctionTool
        from autogen_ext.models.anthropic import AnthropicChatCompletionClient
    except Exception as e:
        return {"verdict": "INSTALL_FAILED", "error": str(e)[:200]}

    captured = {"code": ""}
    def write_code(content: str) -> str:
        """Write the Python function code."""
        captured["code"] = content
        return f"wrote {len(content)} bytes"
    try:
        synapse.install(framework="autogen", bus_url=REDIS_URL, state_dsn=PG_DSN)
        client = AnthropicChatCompletionClient(
            model=ANTHROPIC_MODEL,
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            model_info={"vision": False, "function_calling": True,
                       "json_output": False, "family": "claude-haiku-4-5",
                       "structured_output": False},
        )
        tool = FunctionTool(write_code, description="Write the fizzbuzz function code")
        agent = AssistantAgent(name="builder", model_client=client, tools=[tool],
                              system_message="You write Python code via the write_code tool.")
        await asyncio.wait_for(
            agent.on_messages([TextMessage(content=FIZZBUZZ_PROMPT, source="user")],
                             cancellation_token=CancellationToken()),
            timeout=90,
        )
        return _verdict_from_code(captured["code"])
    except Exception as e:
        return {"verdict": "EXAMPLE_FAILED", "error": f"{type(e).__name__}: {str(e)[:300]}"}


async def build_crewai(session: str) -> dict:
    os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"
    os.environ["OTEL_SDK_DISABLED"] = "true"
    os.environ["SYNAPSE_SESSION_ID"] = session
    import synapse
    try:
        from crewai import Agent, Task, Crew, Process
        from crewai.tools import tool as crew_tool
    except Exception as e:
        return {"verdict": "INSTALL_FAILED", "error": str(e)[:200]}

    captured = {"code": ""}
    @crew_tool("write_code")
    def write_code(content: str) -> str:
        """Write the Python function code."""
        captured["code"] = content
        return f"wrote {len(content)} bytes"
    try:
        synapse.install(framework="crewai", bus_url=REDIS_URL, state_dsn=PG_DSN)
        llm = f"anthropic/{ANTHROPIC_MODEL}"
        agent = Agent(role="Python Coder", goal="Write fizzbuzz",
                     backstory="You write clean Python.",
                     allow_delegation=False, verbose=False,
                     tools=[write_code], llm=llm)
        task = Task(description=FIZZBUZZ_PROMPT,
                   expected_output="code written via write_code", agent=agent)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential,
                   verbose=False, memory=False, cache=False)
        await asyncio.wait_for(asyncio.to_thread(crew.kickoff), timeout=120)
        return _verdict_from_code(captured["code"])
    except Exception as e:
        return {"verdict": "EXAMPLE_FAILED", "error": f"{type(e).__name__}: {str(e)[:300]}"}


async def build_langgraph(session: str) -> dict:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    try:
        from langchain_anthropic import ChatAnthropic
        from langgraph.prebuilt import create_react_agent
        from langchain_core.tools import tool as lc_tool
    except Exception as e:
        return {"verdict": "INSTALL_FAILED", "error": str(e)[:200]}

    captured = {"code": ""}
    @lc_tool
    def write_code(content: str) -> str:
        """Write the Python function code."""
        captured["code"] = content
        return f"wrote {len(content)} bytes"
    try:
        synapse.install(framework="langgraph", bus_url=REDIS_URL, state_dsn=PG_DSN)
        llm = ChatAnthropic(model=ANTHROPIC_MODEL, max_tokens=400, temperature=0)
        agent = create_react_agent(llm, tools=[write_code], name="builder")
        await asyncio.wait_for(
            agent.ainvoke({"messages": [{"role": "user", "content": FIZZBUZZ_PROMPT}]}),
            timeout=90,
        )
        return _verdict_from_code(captured["code"])
    except Exception as e:
        return {"verdict": "EXAMPLE_FAILED", "error": f"{type(e).__name__}: {str(e)[:300]}"}


async def build_hermes(session: str) -> dict:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    try:
        from synapse.bus import Bus
        from synapse.state import StateGraph
        from synapse.integrations.hermes_integration import (
            install_hermes_synapse_hooks, wrap_tool_call_for_synapse, clear_runtime,
        )
        from anthropic import AsyncAnthropic
    except Exception as e:
        return {"verdict": "INSTALL_FAILED", "error": str(e)[:200]}

    bus = Bus(REDIS_URL); state = StateGraph(PG_DSN)
    await bus.connect(); await state.connect()
    try:
        clear_runtime()
        await install_hermes_synapse_hooks(bus=bus, state=state, session_id=session,
                                          agent_id="builder", gate_ms=200)
        ant = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        captured = {"code": ""}
        msg = await ant.messages.create(model=ANTHROPIC_MODEL, max_tokens=400,
            messages=[{"role": "user", "content": FIZZBUZZ_PROMPT.replace("Call the write_code tool", "Just output the function")}])
        text = msg.content[0].text if msg.content else ""

        async def actual_write():
            captured["code"] = text
            return f"wrote {len(text)} bytes"
        await wrap_tool_call_for_synapse("write_code", {"content": text}, actual_write,
                                        agent_id="builder")
        return _verdict_from_code(captured["code"])
    except Exception as e:
        return {"verdict": "EXAMPLE_FAILED", "error": f"{type(e).__name__}: {str(e)[:300]}"}
    finally:
        try: await bus.disconnect()
        except Exception: pass
        try: await state.disconnect()
        except Exception: pass


async def build_smolagents(session: str) -> dict:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    try:
        from smolagents import CodeAgent, Tool, LiteLLMModel
    except Exception as e:
        return {"verdict": "INSTALL_FAILED", "error": str(e)[:200]}

    captured = {"code": ""}
    class WriteCode(Tool):
        name = "write_code"
        description = "Write the Python function code to disk"
        inputs = {"content": {"type": "string", "description": "Full python source"}}
        output_type = "string"
        def forward(self, content: str) -> str:
            captured["code"] = content
            return f"wrote {len(content)} bytes"
    try:
        synapse.install(framework="smolagents", bus_url=REDIS_URL, state_dsn=PG_DSN)
        model = LiteLLMModel(model_id=f"anthropic/{ANTHROPIC_MODEL}",
                            api_key=os.environ.get("ANTHROPIC_API_KEY"))
        agent = CodeAgent(tools=[WriteCode()], model=model, max_steps=3)
        await asyncio.wait_for(asyncio.to_thread(agent.run, FIZZBUZZ_PROMPT), timeout=120)
        return _verdict_from_code(captured["code"])
    except Exception as e:
        return {"verdict": "EXAMPLE_FAILED", "error": f"{type(e).__name__}: {str(e)[:300]}"}


async def build_agno(session: str) -> dict:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    try:
        from agno.agent import Agent
        from agno.models.anthropic import Claude
    except Exception as e:
        return {"verdict": "INSTALL_FAILED", "error": str(e)[:200]}

    captured = {"code": ""}
    def write_code(content: str) -> str:
        """Write the Python function code."""
        captured["code"] = content
        return f"wrote {len(content)} bytes"
    try:
        synapse.install(framework="agno", bus_url=REDIS_URL, state_dsn=PG_DSN)
        agent = Agent(model=Claude(id=ANTHROPIC_MODEL,
                                  api_key=os.environ.get("ANTHROPIC_API_KEY")),
                     tools=[write_code], instructions="Call write_code with the function.")
        await asyncio.wait_for(asyncio.to_thread(agent.run, FIZZBUZZ_PROMPT), timeout=120)
        return _verdict_from_code(captured["code"])
    except Exception as e:
        return {"verdict": "EXAMPLE_FAILED", "error": f"{type(e).__name__}: {str(e)[:300]}"}


async def build_llama_index(session: str) -> dict:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    try:
        from llama_index.core.agent import ReActAgent
        from llama_index.core.tools import FunctionTool
        from llama_index.llms.anthropic import Anthropic
    except Exception as e:
        return {"verdict": "INSTALL_FAILED", "error": str(e)[:200]}

    captured = {"code": ""}
    def write_code(content: str) -> str:
        """Write the Python function code."""
        captured["code"] = content
        return f"wrote {len(content)} bytes"
    try:
        synapse.install(framework="llama_index", bus_url=REDIS_URL, state_dsn=PG_DSN)
        tool = FunctionTool.from_defaults(fn=write_code)
        llm = Anthropic(model=ANTHROPIC_MODEL,
                       api_key=os.environ.get("ANTHROPIC_API_KEY"))
        agent = ReActAgent(tools=[tool], llm=llm, max_iterations=3, verbose=False)
        await asyncio.wait_for(asyncio.to_thread(agent.chat, FIZZBUZZ_PROMPT), timeout=120)
        return _verdict_from_code(captured["code"])
    except Exception as e:
        return {"verdict": "EXAMPLE_FAILED", "error": f"{type(e).__name__}: {str(e)[:300]}"}


async def build_pydantic_ai(session: str) -> dict:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    try:
        from pydantic_ai import Agent
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider
    except Exception as e:
        return {"verdict": "INSTALL_FAILED", "error": str(e)[:200]}

    captured = {"code": ""}
    try:
        synapse.install(framework="pydantic_ai", bus_url=REDIS_URL, state_dsn=PG_DSN)
        provider = AnthropicProvider(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        model = AnthropicModel(ANTHROPIC_MODEL, provider=provider)
        agent = Agent(model, system_prompt="Use write_code to write the function.")
        @agent.tool_plain
        def write_code(content: str) -> str:
            """Write Python code."""
            captured["code"] = content
            return f"wrote {len(content)} bytes"
        await asyncio.wait_for(agent.run(FIZZBUZZ_PROMPT), timeout=120)
        return _verdict_from_code(captured["code"])
    except Exception as e:
        return {"verdict": "EXAMPLE_FAILED", "error": f"{type(e).__name__}: {str(e)[:300]}"}


async def build_openai_agents(session: str) -> dict:
    """openai_agents via LitellmModel→Anthropic (NOT via OpenAI proxy)."""
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    try:
        from agents import Agent, Runner, function_tool
        from agents.extensions.models.litellm_model import LitellmModel
    except Exception as e:
        return {"verdict": "INSTALL_FAILED", "error": str(e)[:200]}

    captured = {"code": ""}
    @function_tool
    def write_code(content: str) -> str:
        """Write the Python function code."""
        captured["code"] = content
        return f"wrote {len(content)} bytes"
    try:
        synapse.install(framework="openai_agents", bus_url=REDIS_URL, state_dsn=PG_DSN)
        model = LitellmModel(model=f"anthropic/{ANTHROPIC_MODEL}",
                            api_key=os.environ.get("ANTHROPIC_API_KEY"))
        # Track C: retry once if LLM didn't call the tool (cooperative wrapper)
        agent = Agent(name="builder", model=model, tools=[write_code],
                     instructions="Call write_code with the Python fizzbuzz function. "
                                  "You MUST call write_code exactly once.")
        for attempt in range(2):  # one retry on no-tool-call
            await asyncio.wait_for(
                Runner.run(agent, FIZZBUZZ_PROMPT),
                timeout=90,
            )
            if captured["code"]:
                break
        return _verdict_from_code(captured["code"])
    except Exception as e:
        return {"verdict": "EXAMPLE_FAILED", "error": f"{type(e).__name__}: {str(e)[:300]}"}


async def build_google_adk(session: str) -> dict:
    """google_adk is heavy (needs SessionService for full Runner). Smoke
    test: install + construct Agent + verify the adapter patched the
    tool dispatch path (full run requires a Runner harness)."""
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    try:
        from google.adk.agents import Agent
        from google.adk.tools import FunctionTool
    except Exception as e:
        return {"verdict": "INSTALL_FAILED", "error": str(e)[:200]}

    def write_code(content: str) -> str:
        """Write the Python function code."""
        return f"wrote {len(content)} bytes"
    try:
        synapse.install(framework="google_adk", bus_url=REDIS_URL, state_dsn=PG_DSN)
        agent = Agent(name="builder", model="gemini-2.5-flash",
                     instruction=FIZZBUZZ_PROMPT,
                     tools=[FunctionTool(write_code)])
        # Construct only — full run needs Runner+Session+InvocationContext.
        # The smoke verdict is "adapter loaded + agent constructed".
        return {"verdict": "V1_SMOKE_ONLY",
                "note": "agent constructed; full Runner requires SessionService"}
    except Exception as e:
        return {"verdict": "EXAMPLE_FAILED", "error": f"{type(e).__name__}: {str(e)[:300]}"}


def _verdict_from_code(code: str) -> dict:
    if not code or len(code.strip()) < 10:
        return {"verdict": "V1_FAILED",
                "error": f"no code captured (len={len(code or '')})",
                "code_preview": (code or "")[:300]}
    passed, reason = execute_and_verify(code)
    if passed:
        return {"verdict": "V1_PASS", "reason": reason,
                "code_preview": code[:300]}
    return {"verdict": "V1_FAILED", "error": reason,
            "code_preview": code[:300]}


# ============================================================================
# Driver
# ============================================================================
BUILDERS = [
    ("autogen",        build_autogen),
    ("crewai",         build_crewai),
    ("langgraph",      build_langgraph),
    ("hermes",         build_hermes),
    ("smolagents",     build_smolagents),
    ("agno",           build_agno),
    ("llama_index",    build_llama_index),
    ("pydantic_ai",    build_pydantic_ai),
    ("openai_agents",  build_openai_agents),
    ("google_adk",     build_google_adk),
]


PER_TEST_TIMEOUT_S = 200


async def main() -> None:
    import synapse
    print(f"=== v19 END-TO-END V1 PRODUCT BUILDS ===")
    print(f"  synapse v{synapse.__version__}")
    print(f"  spec: produce a Python fizzbuzz() that passes 6 assertions")
    print(f"  LLM: {ANTHROPIC_MODEL}")
    await apply_migrations()

    summary: dict[str, dict] = {}
    for name, fn in BUILDERS:
        print(f"\n=========== {name} ===========", flush=True)
        sess = f"v19_{name}_{int(time.time())}"
        t0 = time.monotonic()
        try:
            r = await asyncio.wait_for(fn(sess), timeout=PER_TEST_TIMEOUT_S)
        except asyncio.TimeoutError:
            r = {"verdict": "EXAMPLE_FAILED",
                 "error": f"per-test timeout {PER_TEST_TIMEOUT_S}s"}
        except Exception as e:
            r = {"verdict": "EXAMPLE_FAILED",
                 "error": f"{type(e).__name__}: {str(e)[:200]}",
                 "tb": traceback.format_exc()[-300:]}
        elapsed = time.monotonic() - t0
        try:
            stats = await query_session_intents(sess)
        except Exception:
            stats = {"intents": 0, "agents": []}
        r["intents"] = stats["intents"]
        r["agents"] = stats["agents"]
        r["elapsed_s"] = round(elapsed, 1)
        summary[name] = r
        print(f"  verdict={r.get('verdict','?')}")
        if r.get("reason"): print(f"  reason: {r['reason']}")
        if r.get("error"): print(f"  ERROR: {r['error']}")
        print(f"  intents={r['intents']} agents={r['agents']}")
        if r.get("code_preview"): print(f"  code preview: {r['code_preview'][:200]!r}")

    print("\n" + "=" * 100)
    print("  v19 END-TO-END V1 BUILD SUMMARY")
    print("=" * 100)
    pass_count = 0
    smoke_count = 0
    for name, _ in BUILDERS:
        s = summary[name]
        v = s.get("verdict", "?")
        marker = "PASS" if v == "V1_PASS" else ("SMOKE" if v == "V1_SMOKE_ONLY" else "FAIL")
        print(f"  {marker:<6} {name:<16} verdict={v:<25} intents={s['intents']:<3} elapsed={s['elapsed_s']:>6}s")
        if v == "V1_PASS": pass_count += 1
        elif v == "V1_SMOKE_ONLY": smoke_count += 1
    print(f"\n  V1_PASS: {pass_count}/{len(BUILDERS)}   V1_SMOKE: {smoke_count}/{len(BUILDERS)}")

    out = f"/tmp/public_benchmark_v19_{int(time.time())}.json"
    with open(out, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
