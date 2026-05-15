"""LangGraph orchestrator: Drafter is a create_react_agent with a @tool."""
from __future__ import annotations
import asyncio, os, time
from pathlib import Path
import synapse
from shared.spec import SCOPES, StepResult
from shared.runner_base import RunContext
from orchestrators._template_helpers import (
    setup_session, step_S1_parse, step_S2_match, step_S3_scrub,
    step_S5_validate, step_S6_submit, finalize,
)


async def _s4_langgraph_draft(ctx: RunContext) -> None:
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent
    from langchain_core.tools import tool as lc_tool

    async with synapse.intend(
        scope=SCOPES["S4_draft_letters"], agent="langgraph_drafter",
        session=ctx.session_id,
        expected_outcome="draft 5 cover letters via LangGraph ReAct",
    ) as i:
        t0 = time.monotonic()
        # Real LLM draft (the heavy LLM call done directly)
        for jm in ctx.matched_roles[:5]:
            jid = jm.get("job_id") or jm.get("id") or ""
            job = next((j for j in ctx.all_jobs if j.id == jid), None)
            if job is None: continue
            ctx.cover_letters[jid] = await ctx.llm_draft_letter(job)

        # Have a LangGraph ReAct agent register them via a tool — exercises
        # the synapse-langgraph adapter's `register_configure_hook` path
        @lc_tool
        def register_letter(job_id: str, letter_bytes: int) -> str:
            """Register a drafted letter for audit."""
            return f"registered {job_id}: {letter_bytes}B"

        llm = ChatOpenAI(model=os.environ.get("PRESSURE_TEST_MODEL", "gpt-4o-mini"),
                        max_tokens=200, temperature=0,
                        api_key=os.environ.get("OPENAI_API_KEY"))
        agent = create_react_agent(llm, tools=[register_letter],
                                   name="letter_registrar")
        msg = "Call register_letter for each: " + ", ".join(
            f"job_id={jid}, letter_bytes={len(l)}"
            for jid, l in list(ctx.cover_letters.items())[:5])
        try:
            await agent.ainvoke({"messages": [{"role": "user", "content": msg}]})
        except Exception as e:
            ctx.summary.notes.append(f"langgraph register-letter soft-failed: {e}")

        ctx.summary.steps.append(StepResult(
            step="S4_draft_letters", role="langgraph_drafter",
            intention_id=i.intention_id, has_conflicts=i.has_conflicts,
            elapsed_s=round(time.monotonic() - t0, 2),
            output_bytes=sum(len(v) for v in ctx.cover_letters.values())))


async def run(redis_url: str, pg_dsn: str, out_dir: Path) -> RunContext:
    ctx = RunContext("langgraph", out_dir)
    await setup_session(ctx, "langgraph", redis_url, pg_dsn)
    await step_S1_parse(ctx); await step_S2_match(ctx); await step_S3_scrub(ctx)
    await asyncio.gather(_s4_langgraph_draft(ctx), step_S5_validate(ctx))
    await step_S6_submit(ctx)
    await finalize(ctx, pg_dsn, redis_url)
    return ctx
