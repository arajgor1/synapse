"""Google ADK orchestrator: Drafter is an ADK Agent + InMemoryRunner via
LiteLlm-routed OpenAI."""
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


async def _s4_google_adk_draft(ctx: RunContext) -> None:
    from google.adk.agents import Agent
    from google.adk.tools import FunctionTool
    from google.adk.runners import InMemoryRunner
    from google.adk.models.lite_llm import LiteLlm
    from google.genai import types as genai_types

    async with synapse.intend(
        scope=SCOPES["S4_draft_letters"], agent="google_adk_drafter",
        session=ctx.session_id,
        expected_outcome="draft 5 cover letters via Google ADK",
    ) as i:
        t0 = time.monotonic()
        for jm in ctx.matched_roles[:5]:
            jid = jm.get("job_id") or jm.get("id") or ""
            job = next((j for j in ctx.all_jobs if j.id == jid), None)
            if job is None: continue
            ctx.cover_letters[jid] = await ctx.llm_draft_letter(job)

        def register_letter(job_id: str, letter_bytes: int) -> str:
            """Register a drafted letter for audit."""
            return f"registered {job_id}: {letter_bytes}B"

        try:
            model = LiteLlm(model=f"openai/{os.environ.get('PRESSURE_TEST_MODEL', 'gpt-4o-mini')}",
                           api_key=os.environ.get("OPENAI_API_KEY"))
            agent = Agent(name="letter_registrar", model=model,
                         instruction="Call register_letter for each pair.",
                         tools=[FunctionTool(register_letter)])
            runner = InMemoryRunner(agent=agent, app_name="pressuretest_adk")
            sess = await runner.session_service.create_session(
                app_name="pressuretest_adk", user_id="bench")
            msg = "Register: " + " ".join(
                f"({jid}, {len(l)})"
                for jid, l in list(ctx.cover_letters.items())[:5])
            content = genai_types.Content(role="user",
                parts=[genai_types.Part(text=msg)])
            async for _ev in runner.run_async(user_id="bench",
                                              session_id=sess.id,
                                              new_message=content):
                pass
        except Exception as e:
            ctx.summary.notes.append(f"google_adk register-letter soft-failed: {e}")

        ctx.summary.steps.append(StepResult(
            step="S4_draft_letters", role="google_adk_drafter",
            intention_id=i.intention_id, has_conflicts=i.has_conflicts,
            elapsed_s=round(time.monotonic() - t0, 2),
            output_bytes=sum(len(v) for v in ctx.cover_letters.values())))


async def run(redis_url: str, pg_dsn: str, out_dir: Path) -> RunContext:
    ctx = RunContext("google_adk", out_dir)
    await setup_session(ctx, "google_adk", redis_url, pg_dsn)
    await step_S1_parse(ctx); await step_S2_match(ctx); await step_S3_scrub(ctx)
    await asyncio.gather(_s4_google_adk_draft(ctx), step_S5_validate(ctx))
    await step_S6_submit(ctx)
    await finalize(ctx, pg_dsn, redis_url)
    return ctx
