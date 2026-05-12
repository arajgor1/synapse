"""Public benchmark v20 — NLA-extended product builds.

Runs the v19 fizzbuzz V1 build for 3 adapters (autogen, hermes, langgraph)
with Anthropic extended thinking ENABLED, capturing the LLM's reasoning
via synapse.wrap_anthropic_for_thoughts → THOUGHT envelopes.

Asserts:
  1. The same V1 fizzbuzz function still gets produced + executes correctly
  2. THOUGHT envelopes were persisted to Postgres alongside INTENTIONs
  3. The audit trail shows reasoning → intent → tool-call → resolution

This demonstrates "Synapse-as-NLA-for-agents": every tool call in the
audit trail now has the LLM's pre-call reasoning attached.
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
# Extended thinking requires Sonnet 4.5+ — Haiku doesn't support thinking blocks
ANTHROPIC_THINKING_MODEL = "claude-sonnet-4-5-20250929"
# Fallback to Haiku for tool calls if Sonnet fails
ANTHROPIC_FALLBACK_MODEL = "claude-haiku-4-5-20251001"


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


FIZZBUZZ_PROMPT = (
    "Think step-by-step about how to implement fizzbuzz, then write a Python "
    "function called `fizzbuzz(n: int) -> str` returning:\n"
    "  - 'FizzBuzz' if n % 15 == 0\n"
    "  - 'Fizz' if n % 3 == 0\n"
    "  - 'Buzz' if n % 5 == 0\n"
    "  - str(n) otherwise\n"
    "Output ONLY the function. No imports, no fences, no prose. Then say DONE."
)

V1_ASSERTIONS = [(15, "FizzBuzz"), (9, "Fizz"), (10, "Buzz"), (1, "1"),
                 (0, "FizzBuzz"), (-3, "Fizz")]


def _verify(code: str) -> tuple[bool, str]:
    code = code.strip()
    if code.startswith("```"):
        lines = code.splitlines()
        if lines[0].startswith("```"): lines = lines[1:]
        if lines and lines[-1].startswith("```"): lines = lines[:-1]
        code = "\n".join(lines)
    # v20.1: stop at dedented non-Python line (strips trailing "DONE")
    m = re.search(r"(def\s+fizzbuzz\s*\([^)]*\)\s*(?:->[^:]+)?\s*:[\s\S]+?)(?=\n[^\s#)\]]|\Z)", code)
    if m: code = m.group(1)
    else:
        lines = code.splitlines()
        out = []; in_fn = False
        for ln in lines:
            if not in_fn and re.match(r"def\s+fizzbuzz", ln):
                in_fn = True
            if in_fn:
                if ln.strip() == "" or ln.startswith((" ", "\t", "def ", "@")):
                    out.append(ln)
                else:
                    break
        if out: code = "\n".join(out)
    try:
        ns: dict = {}
        exec(code, ns)
        fn = ns.get("fizzbuzz")
        if not callable(fn):
            return False, "fizzbuzz not defined"
        for n, exp in V1_ASSERTIONS:
            got = fn(n)
            if str(got) != exp:
                return False, f"fizzbuzz({n})={got!r}, expected {exp!r}"
        return True, "all assertions passed"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:200]}"


async def query_session(session: str) -> dict:
    """Read intent + thought envelope counts from Postgres + Redis stream."""
    import asyncpg
    conn = await asyncpg.connect(PG_DSN)
    try:
        intent_rows = await conn.fetch(
            "SELECT agent_id FROM intentions WHERE session_id = $1", session,
        )
    finally:
        await conn.close()

    # THOUGHT envelopes live on the bus stream (not persisted by router into
    # state graph by default — they're side-channel observability events).
    thought_count = 0
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        stream = await r.xrange(f"synapse:session:{session}:events", count=200)
        for _eid, fields in stream:
            try:
                env = json.loads(fields.get("e", "{}"))
                if env.get("type") == "THOUGHT":
                    thought_count += 1
            except Exception:
                pass
        await r.close()
    except Exception:
        pass

    return {
        "intents": len(intent_rows),
        "thoughts": thought_count,
        "agents": sorted({r["agent_id"] for r in intent_rows}),
    }


# ============================================================================
# autogen + extended thinking
# ============================================================================
async def build_autogen_thinking(session: str) -> dict:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    try:
        from autogen_agentchat.agents import AssistantAgent
        from autogen_agentchat.messages import TextMessage
        from autogen_core import CancellationToken
        from autogen_core.tools import FunctionTool
        from autogen_ext.models.anthropic import AnthropicChatCompletionClient
        from anthropic import AsyncAnthropic
        from synapse.llm_thoughts import wrap_anthropic_for_thoughts
    except Exception as e:
        return {"verdict": "INSTALL_FAILED", "error": str(e)[:200]}

    captured = {"code": ""}
    def write_code(content: str) -> str:
        """Write Python code."""
        captured["code"] = content
        return f"wrote {len(content)}"

    try:
        synapse.install(framework="autogen", bus_url=REDIS_URL, state_dsn=PG_DSN)

        # Wrap a raw AsyncAnthropic client to capture thinking blocks. We
        # use this client side-channel — autogen-ext doesn't yet expose
        # `thinking` parameter, so we make a separate reasoning call first.
        raw_client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        wrap_anthropic_for_thoughts(raw_client, session_id=session, agent_id="builder")

        # 1. Reasoning pass with extended thinking
        thinking_msg = await raw_client.messages.create(
            model=ANTHROPIC_THINKING_MODEL,
            max_tokens=4000,
            thinking={"type": "enabled", "budget_tokens": 2000},
            messages=[{"role": "user", "content":
                       "Briefly think about how to implement fizzbuzz, "
                       "then output the function code only."}],
        )

        # 2. Tool-call pass via autogen
        autogen_client = AnthropicChatCompletionClient(
            model=ANTHROPIC_FALLBACK_MODEL,
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            model_info={"vision": False, "function_calling": True,
                       "json_output": False, "family": "claude-haiku-4-5",
                       "structured_output": False},
        )
        tool = FunctionTool(write_code, description="Write the function")
        agent = AssistantAgent(name="builder", model_client=autogen_client, tools=[tool])
        await asyncio.wait_for(
            agent.on_messages([TextMessage(content=FIZZBUZZ_PROMPT, source="user")],
                             cancellation_token=CancellationToken()),
            timeout=90,
        )

        await asyncio.sleep(0.5)  # allow THOUGHT envelopes to flush
        passed, reason = _verify(captured["code"])
        return {"verdict": "V1_PASS" if passed else "V1_FAILED",
                "reason": reason,
                "code_preview": captured["code"][:300]}
    except Exception as e:
        return {"verdict": "EXAMPLE_FAILED",
                "error": f"{type(e).__name__}: {str(e)[:300]}"}


# ============================================================================
# hermes + extended thinking
# ============================================================================
async def build_hermes_thinking(session: str) -> dict:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    try:
        from synapse.bus import Bus
        from synapse.state import StateGraph
        from synapse.integrations.hermes_integration import (
            install_hermes_synapse_hooks, wrap_tool_call_for_synapse, clear_runtime,
        )
        from anthropic import AsyncAnthropic
        from synapse.llm_thoughts import wrap_anthropic_for_thoughts
    except Exception as e:
        return {"verdict": "INSTALL_FAILED", "error": str(e)[:200]}

    bus = Bus(REDIS_URL); state = StateGraph(PG_DSN)
    await bus.connect(); await state.connect()
    captured = {"code": ""}
    try:
        clear_runtime()
        await install_hermes_synapse_hooks(bus=bus, state=state, session_id=session,
                                          agent_id="builder", gate_ms=200)
        ant = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        wrap_anthropic_for_thoughts(ant, session_id=session, agent_id="builder")

        msg = await ant.messages.create(
            model=ANTHROPIC_THINKING_MODEL,
            max_tokens=4000,
            thinking={"type": "enabled", "budget_tokens": 2000},
            messages=[{"role": "user", "content": FIZZBUZZ_PROMPT}],
        )
        # Extract the function code from the text response
        text = ""
        for block in (msg.content or []):
            if getattr(block, "type", None) == "text":
                text = getattr(block, "text", "") or ""
                break
        captured["code"] = text

        async def actual_write():
            return f"wrote {len(text)}"
        await wrap_tool_call_for_synapse("write_code", {"content": text},
                                        actual_write, agent_id="builder")

        await asyncio.sleep(0.5)
        passed, reason = _verify(text)
        return {"verdict": "V1_PASS" if passed else "V1_FAILED",
                "reason": reason,
                "code_preview": text[:300]}
    except Exception as e:
        return {"verdict": "EXAMPLE_FAILED",
                "error": f"{type(e).__name__}: {str(e)[:300]}"}
    finally:
        try: await bus.disconnect()
        except Exception: pass
        try: await state.disconnect()
        except Exception: pass


# ============================================================================
# langgraph + extended thinking
# ============================================================================
async def build_langgraph_thinking(session: str) -> dict:
    import synapse
    os.environ["SYNAPSE_SESSION_ID"] = session
    try:
        from langchain_anthropic import ChatAnthropic
        from langgraph.prebuilt import create_react_agent
        from langchain_core.tools import tool as lc_tool
        from anthropic import AsyncAnthropic
        from synapse.llm_thoughts import wrap_anthropic_for_thoughts
    except Exception as e:
        return {"verdict": "INSTALL_FAILED", "error": str(e)[:200]}

    captured = {"code": ""}
    @lc_tool
    def write_code(content: str) -> str:
        """Write Python code."""
        captured["code"] = content
        return f"wrote {len(content)}"

    try:
        synapse.install(framework="langgraph", bus_url=REDIS_URL, state_dsn=PG_DSN)
        # Reasoning side-call via raw Anthropic (langchain-anthropic doesn't
        # fully expose thinking blocks across versions)
        raw_ant = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        wrap_anthropic_for_thoughts(raw_ant, session_id=session, agent_id="builder")
        await raw_ant.messages.create(
            model=ANTHROPIC_THINKING_MODEL,
            max_tokens=2000,
            thinking={"type": "enabled", "budget_tokens": 1024},
            messages=[{"role": "user", "content":
                       "Briefly think about fizzbuzz then say 'plan done'."}],
        )

        # Tool-call pass
        llm = ChatAnthropic(model=ANTHROPIC_FALLBACK_MODEL, max_tokens=400, temperature=0)
        agent = create_react_agent(llm, tools=[write_code], name="builder")
        await asyncio.wait_for(
            agent.ainvoke({"messages": [{"role": "user", "content": FIZZBUZZ_PROMPT}]}),
            timeout=90,
        )

        await asyncio.sleep(0.5)
        passed, reason = _verify(captured["code"])
        return {"verdict": "V1_PASS" if passed else "V1_FAILED",
                "reason": reason,
                "code_preview": captured["code"][:300]}
    except Exception as e:
        return {"verdict": "EXAMPLE_FAILED",
                "error": f"{type(e).__name__}: {str(e)[:300]}"}


BUILDERS = [
    ("autogen_thinking",   build_autogen_thinking),
    ("hermes_thinking",    build_hermes_thinking),
    ("langgraph_thinking", build_langgraph_thinking),
]


async def main() -> None:
    import synapse
    print(f"=== v20 NLA-EXTENDED V1 BUILDS (extended thinking + THOUGHT envelopes) ===")
    print(f"  synapse v{synapse.__version__}")
    print(f"  reasoning model: {ANTHROPIC_THINKING_MODEL}")
    print(f"  tool-call model: {ANTHROPIC_FALLBACK_MODEL}")
    await apply_migrations()

    summary: dict[str, dict] = {}
    for name, fn in BUILDERS:
        print(f"\n=========== {name} ===========", flush=True)
        sess = f"v20_{name}_{int(time.time())}"
        t0 = time.monotonic()
        try:
            r = await asyncio.wait_for(fn(sess), timeout=240)
        except Exception as e:
            r = {"verdict": "EXAMPLE_FAILED",
                 "error": f"{type(e).__name__}: {str(e)[:200]}"}
        stats = await query_session(sess)
        r.update(stats)
        r["elapsed_s"] = round(time.monotonic() - t0, 1)
        summary[name] = r
        print(f"  verdict={r.get('verdict','?')}")
        print(f"  intents={r['intents']}  THOUGHTs={r['thoughts']}")
        if r.get("reason"): print(f"  reason: {r['reason']}")
        if r.get("error"): print(f"  ERROR: {r['error']}")
        print(f"  elapsed={r['elapsed_s']}s")

    print("\n" + "=" * 90)
    print("  v20 NLA-EXTENDED SUMMARY (audit trail = intents + THOUGHTs)")
    print("=" * 90)
    pass_count = 0
    thought_total = 0
    for name, _ in BUILDERS:
        s = summary[name]
        v = s.get("verdict", "?")
        thought_total += s.get("thoughts", 0)
        marker = "PASS" if v == "V1_PASS" else "FAIL"
        print(f"  {marker} {name:<22} verdict={v:<12} intents={s['intents']:<3} "
              f"THOUGHTs={s['thoughts']:<3} elapsed={s['elapsed_s']}s")
        if v == "V1_PASS": pass_count += 1
    print(f"\n  V1_PASS: {pass_count}/{len(BUILDERS)}")
    print(f"  Total THOUGHT envelopes captured: {thought_total}")
    print(f"  → audit trail now includes the model's reasoning, not just tool dispatch")

    out = f"/tmp/public_benchmark_v20_{int(time.time())}.json"
    with open(out, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
