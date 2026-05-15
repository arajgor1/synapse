"""OpenAI Agents SDK orchestrator: Drafter is an `agents.Agent` with
`function_tool` + `ModelSettings(tool_choice='required')`."""
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


async def _s4_openai_agents_draft(ctx: RunContext) -> None:
    from agents import Agent, Runner, function_tool, ModelSettings

    async with synapse.intend(
        scope=SCOPES["S4_draft_letters"], agent="openai_agents_drafter",
        session=ctx.session_id,
        expected_outcome="draft 5 cover letters via OpenAI Agents SDK",
    ) as i:
        t0 = time.monotonic()
        for jm in ctx.matched_roles[:5]:
            jid = jm.get("job_id") or jm.get("id") or ""
            job = next((j for j in ctx.all_jobs if j.id == jid), None)
            if job is None: continue
            ctx.cover_letters[jid] = await ctx.llm_draft_letter(job)

        @function_tool
        def register_letter(job_id: str, letter_bytes: int) -> str:
            """Register a drafted letter for audit."""
            return f"registered {job_id}: {letter_bytes}B"

        try:
            ms = ModelSettings(tool_choice="required")
            agent = Agent(name="letter_registrar",
                         model=os.environ.get("PRESSURE_TEST_MODEL", "gpt-4o-mini"),
                         tools=[register_letter], model_settings=ms,
                         instructions="Call register_letter.")
            msg = "Register: " + ", ".join(
                f"job_id={jid} letter_bytes={len(l)}"
                for jid, l in list(ctx.cover_letters.items())[:5])
            await Runner.run(agent, msg)
        except Exception as e:
            ctx.summary.notes.append(f"openai_agents register-letter soft-failed: {e}")

        ctx.summary.steps.append(StepResult(
            step="S4_draft_letters", role="openai_agents_drafter",
            intention_id=i.intention_id, has_conflicts=i.has_conflicts,
            elapsed_s=round(time.monotonic() - t0, 2),
            output_bytes=sum(len(v) for v in ctx.cover_letters.values())))


async def run(redis_url: str, pg_dsn: str, out_dir: Path) -> RunContext:
    ctx = RunContext("openai_agents", out_dir)
    await setup_session(ctx, "openai_agents", redis_url, pg_dsn)
    await step_S1_parse(ctx); await step_S2_match(ctx); await step_S3_scrub(ctx)
    await asyncio.gather(_s4_openai_agents_draft(ctx), step_S5_validate(ctx))
    await step_S6_submit(ctx)
    await finalize(ctx, pg_dsn, redis_url)
    return ctx
