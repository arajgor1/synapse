"""smolagents orchestrator: Drafter is a CodeAgent that calls a Tool."""
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


async def _s4_smolagents_draft(ctx: RunContext) -> None:
    from smolagents import CodeAgent, Tool, LiteLLMModel

    async with synapse.intend(
        scope=SCOPES["S4_draft_letters"], agent="smolagents_drafter",
        session=ctx.session_id,
        expected_outcome="draft 5 cover letters via smolagents CodeAgent",
    ) as i:
        t0 = time.monotonic()
        for jm in ctx.matched_roles[:5]:
            jid = jm.get("job_id") or jm.get("id") or ""
            job = next((j for j in ctx.all_jobs if j.id == jid), None)
            if job is None: continue
            ctx.cover_letters[jid] = await ctx.llm_draft_letter(job)

        class RegisterLetter(Tool):
            name = "register_letter"
            description = "Register a drafted letter for audit."
            inputs = {
                "job_id": {"type": "string", "description": "job id"},
                "letter_bytes": {"type": "integer", "description": "len"},
            }
            output_type = "string"
            def forward(self, job_id: str, letter_bytes: int) -> str:
                return f"registered {job_id}: {letter_bytes}B"

        try:
            model = LiteLLMModel(
                model_id=f"openai/{os.environ.get('PRESSURE_TEST_MODEL', 'gpt-4o-mini')}",
                api_key=os.environ.get("OPENAI_API_KEY"),
            )
            agent = CodeAgent(tools=[RegisterLetter()], model=model, max_steps=3)
            msg = "Call register_letter for each: " + " ".join(
                f"(job_id='{jid}', letter_bytes={len(l)})"
                for jid, l in list(ctx.cover_letters.items())[:5])
            await asyncio.to_thread(agent.run, msg)
        except Exception as e:
            ctx.summary.notes.append(f"smolagents register-letter soft-failed: {e}")

        ctx.summary.steps.append(StepResult(
            step="S4_draft_letters", role="smolagents_drafter",
            intention_id=i.intention_id, has_conflicts=i.has_conflicts,
            elapsed_s=round(time.monotonic() - t0, 2),
            output_bytes=sum(len(v) for v in ctx.cover_letters.values())))


async def run(redis_url: str, pg_dsn: str, out_dir: Path) -> RunContext:
    ctx = RunContext("smolagents", out_dir)
    await setup_session(ctx, "smolagents", redis_url, pg_dsn)
    await step_S1_parse(ctx); await step_S2_match(ctx); await step_S3_scrub(ctx)
    await asyncio.gather(_s4_smolagents_draft(ctx), step_S5_validate(ctx))
    await step_S6_submit(ctx)
    await finalize(ctx, pg_dsn, redis_url)
    return ctx
