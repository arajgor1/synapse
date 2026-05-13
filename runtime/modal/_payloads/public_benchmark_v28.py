"""Public benchmark v28 — CROSS-FRAMEWORK COOPERATIVE APP BUILD.

THE compliance demo: 10 agents from 10 different framework adapters
collaborate via Synapse to build ONE real Flask Todo app from a single
prompt, then the bench EXECUTES the produced app and verifies it works.

Roles (one per adapter):
  - autogen        → API Architect (writes app/api_spec.md)
  - crewai         → Backend Engineer (writes app/main.py)
  - langgraph      → Test Writer (writes app/test_app.py)
  - hermes         → Project Coordinator (writes app/PLAN.md)
  - smolagents     → DB Modeler (writes app/models.py)
  - agno           → Docs Writer (writes app/README.md)
  - llama_index    → Lint Reviewer (writes app/LINT.md)
  - pydantic_ai    → Schema Validator (writes app/schemas.py)
  - openai_agents  → Deploy Engineer (writes app/deploy.sh)
  - google_adk     → Final Reviewer (writes app/REVIEW.md, Gemini)

After all 10 agents finish:
  1. Every intent is in Postgres
  2. Every Anthropic agent emits a THOUGHT envelope
  3. We compile app/main.py + try to import it
  4. We extract the full envelope JSONL as an artifact

This proves Synapse-as-compliance-layer for agentic teams across vendors.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import time
import traceback
from typing import Any

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("DO_NOT_TRACK", "1")

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
)


async def apply_migrations() -> None:
    import asyncpg
    conn = await asyncpg.connect(PG_DSN)
    try: await conn.execute(MIGRATIONS_SQL)
    finally: await conn.close()


APP_DIR = "/tmp/v28_app"
SESSION = f"v28_app_{int(time.time())}"


# Roles and prompts (each agent writes a different file in app/)
ROLES = {
    "autogen": {
        "file": "api_spec.md",
        "prompt": "Write a brief API spec (5 lines max) for a Flask Todo app: GET /todos, POST /todos. Output ONLY the markdown.",
    },
    "crewai": {
        "file": "main.py",
        "prompt": "Write a complete Flask app file with: from flask import Flask, jsonify, request; "
                  "Flask app called `app`; in-memory list `todos = []`; "
                  "GET /todos returns jsonify(todos); "
                  "POST /todos appends request.json and returns jsonify({\"ok\":True}); "
                  "if __name__ == '__main__': app.run(port=5001, debug=False). "
                  "Output ONLY Python code, no fences.",
    },
    "langgraph": {
        "file": "test_app.py",
        "prompt": "Write a Python pytest file that imports the Flask app and does a basic smoke test: "
                  "client = app.test_client(); resp = client.get('/todos'); assert resp.status_code == 200. "
                  "Output ONLY Python code, no fences.",
    },
    "hermes": {
        "file": "PLAN.md",
        "prompt": "Write a 5-line project plan markdown for a Flask Todo app. Output ONLY the markdown.",
    },
    "smolagents": {
        "file": "models.py",
        "prompt": "Write a Python file with one dataclass: @dataclass class Todo: id: int; title: str; done: bool = False. "
                  "Output ONLY Python code, no fences. Import dataclass from dataclasses.",
    },
    "agno": {
        "file": "README.md",
        "prompt": "Write a brief README markdown (10 lines max) for a Flask Todo app project. Output ONLY the markdown.",
    },
    "llama_index": {
        "file": "LINT.md",
        "prompt": "Write a brief 5-line code review markdown for a Flask Todo app. Output ONLY the markdown.",
    },
    "pydantic_ai": {
        "file": "schemas.py",
        "prompt": "Write a Python file with one pydantic model: class TodoSchema(BaseModel): id: int; title: str; done: bool = False. "
                  "Output ONLY Python code, no fences. Import BaseModel from pydantic.",
    },
    "openai_agents": {
        "file": "deploy.sh",
        "prompt": "Write a 3-line bash deploy script with pip install flask, python main.py. Output ONLY the bash, no fences.",
    },
    "google_adk": {
        "file": "REVIEW.md",
        "prompt": "Write a 3-line review markdown approving the Flask Todo app. Output ONLY the markdown.",
    },
}


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"): lines = lines[1:]
        if lines and lines[-1].startswith("```"): lines = lines[:-1]
        text = "\n".join(lines)
    return text


# ============================================================================
# Per-adapter role implementations
# ============================================================================
async def role_autogen(content_capture: dict, session: str) -> None:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    from autogen_agentchat.agents import AssistantAgent
    from autogen_agentchat.messages import TextMessage
    from autogen_core import CancellationToken
    from autogen_core.tools import FunctionTool
    from autogen_ext.models.anthropic import AnthropicChatCompletionClient
    from anthropic import AsyncAnthropic

    role = "autogen"
    file = ROLES[role]["file"]
    def write_artifact(content: str) -> str:
        """Write the artifact."""
        content_capture[role] = _strip_fences(content)
        return f"wrote {len(content)} bytes to {file}"
    synapse.install(framework="autogen", bus_url=REDIS_URL, state_dsn=PG_DSN)
    # Thought capture
    thinking_client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    synapse.wrap_anthropic_for_thoughts(thinking_client, session_id=session, agent_id=role)
    await thinking_client.messages.create(
        model=ANTHROPIC_MODEL, max_tokens=300,
        messages=[{"role": "user", "content": f"As the API Architect, briefly plan."}],
    )
    client = AnthropicChatCompletionClient(
        model=ANTHROPIC_MODEL, api_key=os.environ.get("ANTHROPIC_API_KEY"),
        model_info={"vision": False, "function_calling": True,
                   "json_output": False, "family": "claude-haiku-4-5",
                   "structured_output": False},
    )
    tool = FunctionTool(write_artifact, description=f"Write the {file}")
    agent = AssistantAgent(name="api_architect", model_client=client, tools=[tool])
    await agent.on_messages(
        [TextMessage(content=f"Call write_artifact with: {ROLES[role]['prompt']}", source="user")],
        cancellation_token=CancellationToken(),
    )


async def role_crewai(content_capture: dict, session: str) -> None:
    os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"
    os.environ["OTEL_SDK_DISABLED"] = "true"
    os.environ["SYNAPSE_SESSION_ID"] = session
    import synapse
    from crewai import Agent, Task, Crew, Process
    from crewai.tools import tool as crew_tool
    from anthropic import AsyncAnthropic
    role = "crewai"
    file = ROLES[role]["file"]
    @crew_tool("write_artifact")
    def write_artifact(content: str) -> str:
        """Write the artifact."""
        content_capture[role] = _strip_fences(content)
        return f"wrote to {file}"
    synapse.install(framework="crewai", bus_url=REDIS_URL, state_dsn=PG_DSN)
    thinking_client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    synapse.wrap_anthropic_for_thoughts(thinking_client, session_id=session, agent_id=role)
    await thinking_client.messages.create(
        model=ANTHROPIC_MODEL, max_tokens=300,
        messages=[{"role": "user", "content": "As the Backend Engineer, briefly plan."}],
    )
    llm = f"anthropic/{ANTHROPIC_MODEL}"
    agent = Agent(role="Backend Engineer", goal="Write Flask app",
                 backstory="You code Flask.", allow_delegation=False, verbose=False,
                 tools=[write_artifact], llm=llm)
    task = Task(description=ROLES[role]["prompt"] + " Call write_artifact with the content.",
               expected_output="written", agent=agent)
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential,
               verbose=False, memory=False, cache=False)
    await asyncio.to_thread(crew.kickoff)


async def role_langgraph(content_capture: dict, session: str) -> None:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    from langchain_anthropic import ChatAnthropic
    from langgraph.prebuilt import create_react_agent
    from langchain_core.tools import tool as lc_tool
    from anthropic import AsyncAnthropic
    role = "langgraph"
    file = ROLES[role]["file"]
    @lc_tool
    def write_artifact(content: str) -> str:
        """Write artifact."""
        content_capture[role] = _strip_fences(content)
        return f"wrote to {file}"
    synapse.install(framework="langgraph", bus_url=REDIS_URL, state_dsn=PG_DSN)
    thinking_client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    synapse.wrap_anthropic_for_thoughts(thinking_client, session_id=session, agent_id=role)
    await thinking_client.messages.create(
        model=ANTHROPIC_MODEL, max_tokens=300,
        messages=[{"role": "user", "content": "As Test Writer, briefly plan."}],
    )
    llm = ChatAnthropic(model=ANTHROPIC_MODEL, max_tokens=400, temperature=0)
    agent = create_react_agent(llm, tools=[write_artifact], name="test_writer")
    await agent.ainvoke({"messages": [{"role": "user", "content": ROLES[role]["prompt"]}]})


async def role_hermes(content_capture: dict, session: str) -> None:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    from synapse.bus import Bus
    from synapse.state import StateGraph
    from synapse.integrations.hermes_integration import (
        install_hermes_synapse_hooks, wrap_tool_call_for_synapse, clear_runtime,
    )
    from anthropic import AsyncAnthropic
    role = "hermes"
    file = ROLES[role]["file"]
    bus = Bus(REDIS_URL); state = StateGraph(PG_DSN)
    await bus.connect(); await state.connect()
    try:
        clear_runtime()
        await install_hermes_synapse_hooks(bus=bus, state=state, session_id=session,
                                          agent_id="coordinator", gate_ms=200)
        ant = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        synapse.wrap_anthropic_for_thoughts(ant, session_id=session, agent_id=role)
        msg = await ant.messages.create(model=ANTHROPIC_MODEL, max_tokens=300,
            messages=[{"role": "user", "content": ROLES[role]["prompt"]}])
        text = msg.content[0].text if msg.content else ""
        async def actual_write():
            content_capture[role] = _strip_fences(text)
            return f"wrote to {file}"
        await wrap_tool_call_for_synapse("write_artifact", {"path": file}, actual_write,
                                        agent_id="coordinator")
    finally:
        try: await bus.disconnect()
        except Exception: pass
        try: await state.disconnect()
        except Exception: pass


async def role_smolagents(content_capture: dict, session: str) -> None:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    from smolagents import CodeAgent, Tool, LiteLLMModel
    from anthropic import AsyncAnthropic
    role = "smolagents"
    file = ROLES[role]["file"]
    class WriteArtifact(Tool):
        name = "write_artifact"
        description = "Write the artifact"
        inputs = {"content": {"type": "string", "description": "content"}}
        output_type = "string"
        def forward(self, content: str) -> str:
            content_capture[role] = _strip_fences(content)
            return f"wrote to {file}"
    synapse.install(framework="smolagents", bus_url=REDIS_URL, state_dsn=PG_DSN)
    thinking_client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    synapse.wrap_anthropic_for_thoughts(thinking_client, session_id=session, agent_id=role)
    await thinking_client.messages.create(
        model=ANTHROPIC_MODEL, max_tokens=300,
        messages=[{"role": "user", "content": "As DB Modeler, briefly plan."}],
    )
    model = LiteLLMModel(model_id=f"anthropic/{ANTHROPIC_MODEL}",
                        api_key=os.environ.get("ANTHROPIC_API_KEY"))
    agent = CodeAgent(tools=[WriteArtifact()], model=model, max_steps=3)
    await asyncio.to_thread(agent.run, ROLES[role]["prompt"])


async def role_agno(content_capture: dict, session: str) -> None:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    from agno.agent import Agent
    from agno.models.anthropic import Claude
    from anthropic import AsyncAnthropic
    role = "agno"
    file = ROLES[role]["file"]
    def write_artifact(content: str) -> str:
        """Write artifact."""
        content_capture[role] = _strip_fences(content)
        return f"wrote to {file}"
    synapse.install(framework="agno", bus_url=REDIS_URL, state_dsn=PG_DSN)
    thinking_client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    synapse.wrap_anthropic_for_thoughts(thinking_client, session_id=session, agent_id=role)
    await thinking_client.messages.create(
        model=ANTHROPIC_MODEL, max_tokens=300,
        messages=[{"role": "user", "content": "As Docs Writer, briefly plan."}],
    )
    agent = Agent(model=Claude(id=ANTHROPIC_MODEL,
                              api_key=os.environ.get("ANTHROPIC_API_KEY")),
                 tools=[write_artifact],
                 instructions="Call write_artifact with the content.")
    await asyncio.to_thread(agent.run, ROLES[role]["prompt"])


async def role_llama_index(content_capture: dict, session: str) -> None:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    from llama_index.core.agent.workflow import FunctionAgent
    from llama_index.core.tools import FunctionTool
    from llama_index.llms.anthropic import Anthropic
    from anthropic import AsyncAnthropic
    role = "llama_index"
    file = ROLES[role]["file"]
    def write_artifact(content: str) -> str:
        """Write artifact."""
        content_capture[role] = _strip_fences(content)
        return f"wrote to {file}"
    synapse.install(framework="llama_index", bus_url=REDIS_URL, state_dsn=PG_DSN)
    thinking_client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    synapse.wrap_anthropic_for_thoughts(thinking_client, session_id=session, agent_id=role)
    await thinking_client.messages.create(
        model=ANTHROPIC_MODEL, max_tokens=300,
        messages=[{"role": "user", "content": "As Lint Reviewer, briefly plan."}],
    )
    tool = FunctionTool.from_defaults(fn=write_artifact)
    llm = Anthropic(model=ANTHROPIC_MODEL, api_key=os.environ.get("ANTHROPIC_API_KEY"))
    agent = FunctionAgent(tools=[tool], llm=llm,
                         system_prompt="Call write_artifact with content.")
    result = await agent.run(ROLES[role]["prompt"])
    # Fall through to AgentOutput.response.content if tool didn't capture
    if role not in content_capture or not content_capture[role]:
        try:
            resp = getattr(result, "response", None)
            if resp:
                c = getattr(resp, "content", None)
                if c: content_capture[role] = _strip_fences(str(c))
        except Exception:
            pass


async def role_pydantic_ai(content_capture: dict, session: str) -> None:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    from pydantic_ai import Agent
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider
    from anthropic import AsyncAnthropic
    role = "pydantic_ai"
    file = ROLES[role]["file"]
    synapse.install(framework="pydantic_ai", bus_url=REDIS_URL, state_dsn=PG_DSN)
    thinking_client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    synapse.wrap_anthropic_for_thoughts(thinking_client, session_id=session, agent_id=role)
    await thinking_client.messages.create(
        model=ANTHROPIC_MODEL, max_tokens=300,
        messages=[{"role": "user", "content": "As Schema Validator, briefly plan."}],
    )
    provider = AnthropicProvider(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    model = AnthropicModel(ANTHROPIC_MODEL, provider=provider)
    agent = Agent(model, system_prompt="Use write_artifact.")
    @agent.tool_plain
    def write_artifact(content: str) -> str:
        """Write artifact."""
        content_capture[role] = _strip_fences(content)
        return f"wrote to {file}"
    await agent.run(ROLES[role]["prompt"])


async def role_openai_agents(content_capture: dict, session: str) -> None:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    from agents import Agent, Runner, function_tool, ModelSettings
    from agents.extensions.models.litellm_model import LitellmModel
    from anthropic import AsyncAnthropic
    role = "openai_agents"
    file = ROLES[role]["file"]
    @function_tool
    def write_artifact(content: str) -> str:
        """Write artifact."""
        content_capture[role] = _strip_fences(content)
        return f"wrote to {file}"
    synapse.install(framework="openai_agents", bus_url=REDIS_URL, state_dsn=PG_DSN)
    thinking_client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    synapse.wrap_anthropic_for_thoughts(thinking_client, session_id=session, agent_id=role)
    await thinking_client.messages.create(
        model=ANTHROPIC_MODEL, max_tokens=300,
        messages=[{"role": "user", "content": "As Deploy Engineer, briefly plan."}],
    )
    model = LitellmModel(model=f"anthropic/{ANTHROPIC_MODEL}",
                        api_key=os.environ.get("ANTHROPIC_API_KEY"))
    ms = ModelSettings(tool_choice="required")
    agent = Agent(name="deploy_engineer", model=model, tools=[write_artifact],
                 model_settings=ms, instructions="Call write_artifact.")
    await Runner.run(agent, ROLES[role]["prompt"])


async def role_google_adk(content_capture: dict, session: str) -> None:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    from google.adk.agents import Agent
    from google.adk.tools import FunctionTool
    from google.adk.runners import InMemoryRunner
    from google.genai import types as genai_types
    role = "google_adk"
    file = ROLES[role]["file"]
    def write_artifact(content: str) -> str:
        """Write artifact."""
        content_capture[role] = _strip_fences(content)
        return f"wrote to {file}"
    synapse.install(framework="google_adk", bus_url=REDIS_URL, state_dsn=PG_DSN)
    agent = Agent(name="final_reviewer", model="gemini-2.5-flash",
                 instruction="Call write_artifact.",
                 tools=[FunctionTool(write_artifact)])
    runner = InMemoryRunner(agent=agent, app_name="v28_adk")
    sess = await runner.session_service.create_session(
        app_name="v28_adk", user_id="bench")
    content = genai_types.Content(role="user",
        parts=[genai_types.Part(text=ROLES[role]["prompt"])])
    async for ev in runner.run_async(user_id="bench", session_id=sess.id,
                                     new_message=content):
        pass


# ============================================================================
# Driver
# ============================================================================
async def query_session(session: str) -> dict:
    import asyncpg
    conn = await asyncpg.connect(PG_DSN)
    try:
        rows = await conn.fetch(
            "SELECT agent_id, scope, action FROM intentions WHERE session_id = $1",
            session)
    finally: await conn.close()
    thoughts = 0
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        stream = await r.xrange(f"synapse:session:{session}:events", count=500)
        for _eid, fields in stream:
            try:
                e = json.loads(fields.get("e", "{}"))
                if e.get("type") == "THOUGHT": thoughts += 1
            except Exception: pass
        await r.aclose()
    except Exception: pass
    return {
        "intents": len(rows),
        "thoughts": thoughts,
        "agents": sorted({r["agent_id"] for r in rows}),
        "scopes": sorted({s for r in rows for s in (r["scope"] or [])}),
    }


async def main() -> None:
    import synapse
    print(f"=== v28 CROSS-FRAMEWORK COOPERATIVE APP BUILD ===")
    print(f"  synapse v{synapse.__version__}")
    print(f"  LLM: {ANTHROPIC_MODEL}")
    print(f"  session: {SESSION}")
    await apply_migrations()
    os.makedirs(APP_DIR, exist_ok=True)

    content_capture: dict[str, str] = {}
    # Run roles SEQUENTIALLY so we can see each per-adapter outcome cleanly.
    # (Parallel asyncio.gather works too but adds noise.)
    runners = [
        ("autogen", role_autogen),
        ("crewai", role_crewai),
        ("langgraph", role_langgraph),
        ("hermes", role_hermes),
        ("smolagents", role_smolagents),
        ("agno", role_agno),
        ("llama_index", role_llama_index),
        ("pydantic_ai", role_pydantic_ai),
        ("openai_agents", role_openai_agents),
        ("google_adk", role_google_adk),
    ]
    per_role: dict[str, dict] = {}
    for name, fn in runners:
        print(f"\n--- role: {name} ({ROLES[name]['file']}) ---", flush=True)
        t0 = time.monotonic()
        try:
            await asyncio.wait_for(fn(content_capture, SESSION), timeout=120)
            captured = content_capture.get(name) or ""
            per_role[name] = {"ok": bool(captured),
                              "bytes": len(captured),
                              "preview": captured[:120],
                              "elapsed_s": round(time.monotonic() - t0, 1)}
            print(f"  captured {len(captured)} bytes  ({per_role[name]['elapsed_s']}s)")
        except Exception as e:
            per_role[name] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}",
                              "elapsed_s": round(time.monotonic() - t0, 1)}
            print(f"  ERROR: {per_role[name]['error']}")

    # Write all captured files
    print(f"\n--- writing artifacts to {APP_DIR}/ ---")
    files_written = []
    for role, info in ROLES.items():
        content = content_capture.get(role) or ""
        if content:
            path = os.path.join(APP_DIR, info["file"])
            with open(path, "w") as f:
                f.write(content)
            files_written.append(info["file"])
            print(f"  {info['file']}  ({len(content)} bytes)")

    # Try to compile + import the main.py (the Flask app)
    main_py = os.path.join(APP_DIR, "main.py")
    app_runs = False
    app_reason = "no main.py written"
    if os.path.isfile(main_py):
        # Just compile-check; running the Flask server inside Modal is more
        # involved (port forwarding) — compile + module-import is sufficient
        # to prove the produced code is syntactically valid + importable.
        compile_proc = subprocess.run(
            ["python3", "-c", f"import py_compile; py_compile.compile({main_py!r}, doraise=True); print('compile-ok')"],
            capture_output=True, text=True, timeout=10,
        )
        if compile_proc.returncode == 0:
            # Import + check that `app` exists
            import_proc = subprocess.run(
                ["python3", "-c",
                 f"import sys; sys.path.insert(0, {APP_DIR!r}); "
                 f"import main; assert hasattr(main, 'app'); "
                 f"client = main.app.test_client(); resp = client.get('/todos'); "
                 f"print(f'GET /todos -> {{resp.status_code}}'); "
                 f"assert resp.status_code == 200; print('app-runs')"],
                capture_output=True, text=True, timeout=15,
            )
            if import_proc.returncode == 0 and "app-runs" in import_proc.stdout:
                app_runs = True
                app_reason = "imports OK + Flask test_client GET /todos returned 200"
            else:
                app_reason = f"import/run failed: {import_proc.stderr[:200] or import_proc.stdout[:200]}"
        else:
            app_reason = f"compile failed: {compile_proc.stderr[:200]}"

    # Pull envelopes
    stats = await query_session(SESSION)

    print("\n" + "=" * 90)
    print(f"  v28 SUMMARY: cross-framework cooperative app build (session={SESSION})")
    print("=" * 90)
    captured_count = sum(1 for r in per_role.values() if r.get("ok"))
    print(f"  Roles that wrote artifact: {captured_count}/10")
    print(f"  Files in {APP_DIR}: {files_written}")
    print(f"  Intents persisted: {stats['intents']}")
    print(f"  THOUGHT envelopes: {stats['thoughts']}")
    print(f"  Distinct agents: {stats['agents']}")
    print(f"  App compiles + runs: {app_runs}")
    print(f"  App run check: {app_reason}")

    # Save artifact bundle + envelope JSONL
    artifact_dir = f"/tmp/v28_artifact_{int(time.time())}"
    os.makedirs(artifact_dir, exist_ok=True)
    subprocess.run(["cp", "-r", APP_DIR, os.path.join(artifact_dir, "app")])
    # Export envelope JSONL
    import asyncpg
    conn = await asyncpg.connect(PG_DSN)
    try:
        rows = await conn.fetch(
            "SELECT id, agent_id, session_id, scope, action, expected_outcome, "
            "       status, created_at, resolved_at "
            "FROM intentions WHERE session_id = $1 ORDER BY created_at",
            SESSION)
    finally:
        await conn.close()
    with open(os.path.join(artifact_dir, "envelopes.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps({
                "type": "INTENTION",
                "id": r["id"], "agent_id": r["agent_id"],
                "session_id": r["session_id"], "scope": list(r["scope"] or []),
                "action": r["action"], "expected_outcome": r["expected_outcome"],
                "status": r["status"],
                "ts_ms": int((r["created_at"].timestamp() if r["created_at"] else 0) * 1000),
            }, default=str) + "\n")
    # THOUGHT envelopes from stream
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        stream = await r.xrange(f"synapse:session:{SESSION}:events", count=500)
        with open(os.path.join(artifact_dir, "envelopes.jsonl"), "a") as f:
            for _eid, fields in stream:
                try:
                    env = json.loads(fields.get("e", "{}"))
                    if env.get("type") == "THOUGHT":
                        f.write(json.dumps(env, default=str) + "\n")
                except Exception: pass
        await r.aclose()
    except Exception: pass

    print(f"\n  Artifact bundle: {artifact_dir}/  (app/ + envelopes.jsonl)")
    summary = {
        "session": SESSION,
        "captured_count": captured_count,
        "files_written": files_written,
        "intents": stats["intents"],
        "thoughts": stats["thoughts"],
        "agents": stats["agents"],
        "app_runs": app_runs,
        "app_reason": app_reason,
        "per_role": per_role,
        "artifact_dir": artifact_dir,
    }
    out = f"/tmp/public_benchmark_v28_{int(time.time())}.json"
    with open(out, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
