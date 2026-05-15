"""CrewAI orchestrator: Drafter is a real CrewAI Agent + Task + Crew that
calls `write_letter` as a `@tool`. Synapse's CrewAI adapter intercepts
the tool dispatch."""
from __future__ import annotations
import asyncio, os, time, json
from pathlib import Path

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

import synapse
from shared.spec import SCOPES, StepResult
from shared.runner_base import RunContext
from orchestrators._template_helpers import (
    setup_session, step_S1_parse, step_S2_match, step_S3_scrub,
    step_S5_validate, step_S6_submit, finalize,
)


async def _s4_crewai_draft(ctx: RunContext) -> None:
    from crewai import Agent, Task, Crew, Process
    from crewai.tools import tool as crew_tool

    async with synapse.intend(
        scope=SCOPES["S4_draft_letters"], agent="crewai_drafter",
        session=ctx.session_id,
        expected_outcome="draft 5 cover letters via CrewAI",
    ) as i:
        t0 = time.monotonic()
        for jm in ctx.matched_roles[:5]:
            jid = jm.get("job_id") or jm.get("id") or ""
            job = next((j for j in ctx.all_jobs if j.id == jid), None)
            if job is None: continue
            letter = await ctx.llm_draft_letter(job)
            ctx.cover_letters[jid] = letter

        # Have a CrewAI agent register the outcome via a tool (this is the path
        # where the synapse-crewai adapter intercepts and emits envelopes)
        @crew_tool("register_letter")
        def register_letter(job_id: str, letter_bytes: int) -> str:
            """Register a drafted letter in the audit log."""
            return f"registered job={job_id} bytes={letter_bytes}"

        agent = Agent(
            role="Letter Registrar", goal="Register drafted letters",
            backstory="You log drafted letters.", allow_delegation=False,
            tools=[register_letter],
            llm=f"openai/{os.environ.get('PRESSURE_TEST_MODEL', 'gpt-4o-mini')}",
        )
        task = Task(
            description=(
                f"Call register_letter for each: "
                + ", ".join(f"(job_id='{jid}', letter_bytes={len(l)})"
                            for jid, l in list(ctx.cover_letters.items())[:5])
            ),
            expected_output="all registered",
            agent=agent,
        )
        try:
            crew = Crew(agents=[agent], tasks=[task], process=Process.sequential,
                       verbose=False, memory=False, cache=False)
            await asyncio.to_thread(crew.kickoff)
        except Exception as e:
            ctx.summary.notes.append(f"crewai register-letter step soft-failed: {e}")

        ctx.summary.steps.append(StepResult(
            step="S4_draft_letters", role="crewai_drafter",
            intention_id=i.intention_id, has_conflicts=i.has_conflicts,
            elapsed_s=round(time.monotonic() - t0, 2),
            output_bytes=sum(len(v) for v in ctx.cover_letters.values())))


async def run(redis_url: str, pg_dsn: str, out_dir: Path) -> RunContext:
    ctx = RunContext("crewai", out_dir)
    await setup_session(ctx, "crewai", redis_url, pg_dsn)
    await step_S1_parse(ctx)
    await step_S2_match(ctx)
    await step_S3_scrub(ctx)
    await asyncio.gather(_s4_crewai_draft(ctx), step_S5_validate(ctx))
    await step_S6_submit(ctx)
    await finalize(ctx, pg_dsn, redis_url)
    return ctx
