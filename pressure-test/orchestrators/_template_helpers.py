"""Shared helpers used by every orchestrator. Keeps each orchestrator file
to ~100 LOC of FRAMEWORK-SPECIFIC code (the part being tested).

The pipeline pattern is identical across all 11 frameworks:

  S1 resume_parse  → ctx.llm_parse_resume()    via synapse.intend()
  S2 role_match    → ctx.llm_match_roles()     via synapse.intend()
  S3 scrub_jobs    → scrub.scrub() per job     via synapse.intend()
  S4 draft_letters → FRAMEWORK-SPECIFIC dispatch  ← the bit being tested
  S5 validate_app  → bundle into dict          via synapse.intend()
                     (concurrent w/ S4, overlapping scope to fire L2 router)
  S6 submit_apply  → ctx.mock_submit() per app via synapse.intend()
"""
from __future__ import annotations
import asyncio, json, os, time
from pathlib import Path
from typing import Awaitable, Callable

import synapse
from shared.jobs import fetch_active_jobs
from shared.scrub import scrub
from shared.spec import SCOPES, StepResult
from shared.runner_base import RunContext


async def setup_session(ctx: RunContext, framework: str,
                       redis_url: str, pg_dsn: str) -> None:
    """Common pre-pipeline setup."""
    os.environ["SYNAPSE_SESSION_ID"] = ctx.session_id
    synapse.install(framework=framework, bus_url=redis_url, state_dsn=pg_dsn)
    # PSEUDO_THOUGHT capture via wrap_openai_for_thoughts on a side client
    from openai import AsyncOpenAI
    thinker = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    synapse.wrap_openai_for_thoughts(thinker, session_id=ctx.session_id,
                                     agent_id=f"{framework}_planner")
    await thinker.chat.completions.create(
        model=os.environ.get("PRESSURE_TEST_MODEL", "gpt-4o-mini"),
        max_tokens=150,
        messages=[{"role": "user",
                   "content": f"Plan the 6-step autoapply pipeline."}],
    )

    ctx.resume_text = (Path(__file__).parent.parent / "shared" /
                       "master_resume.txt").read_text(encoding="utf-8")
    ctx.all_jobs = fetch_active_jobs()


async def step_S1_parse(ctx: RunContext) -> None:
    async with synapse.intend(
        scope=SCOPES["S1_resume_parse"], agent="parser",
        session=ctx.session_id,
        expected_outcome="parse resume to JSON",
    ) as i:
        t0 = time.monotonic()
        ctx.parsed_resume = await ctx.llm_parse_resume()
        ctx.summary.steps.append(StepResult(
            step="S1_resume_parse", role="parser",
            intention_id=i.intention_id, has_conflicts=i.has_conflicts,
            elapsed_s=round(time.monotonic() - t0, 2),
            output_bytes=len(json.dumps(ctx.parsed_resume))))


async def step_S2_match(ctx: RunContext) -> None:
    async with synapse.intend(
        scope=SCOPES["S2_role_match"], agent="matcher",
        session=ctx.session_id,
        expected_outcome="rank top 5 jobs",
    ) as i:
        t0 = time.monotonic()
        ctx.matched_roles = await ctx.llm_match_roles()
        ctx.summary.steps.append(StepResult(
            step="S2_role_match", role="matcher",
            intention_id=i.intention_id, has_conflicts=i.has_conflicts,
            elapsed_s=round(time.monotonic() - t0, 2),
            output_bytes=len(json.dumps(ctx.matched_roles))))


async def step_S3_scrub(ctx: RunContext) -> None:
    async with synapse.intend(
        scope=SCOPES["S3_scrub_jobs"], agent="scrubber",
        session=ctx.session_id,
        expected_outcome="strip prompt-injection from job descs",
    ) as i:
        t0 = time.monotonic()
        ctx.scrub_report = {}
        for jm in ctx.matched_roles:
            jid = jm.get("job_id") or jm.get("id") or ""
            job = next((j for j in ctx.all_jobs if j.id == jid), None)
            if job is None: continue
            ctx.scrub_report[jid] = scrub(job.description, launder_fingerprints=False)
        ctx.summary.injections_detected = sum(
            len(s.detections) for s in ctx.scrub_report.values())
        ctx.summary.fingerprints_laundered = sum(
            s.fingerprints_replaced for s in ctx.scrub_report.values())
        ctx.summary.steps.append(StepResult(
            step="S3_scrub_jobs", role="scrubber",
            intention_id=i.intention_id, has_conflicts=i.has_conflicts,
            elapsed_s=round(time.monotonic() - t0, 2),
            output_bytes=sum(len(s.cleaned_text) for s in ctx.scrub_report.values())))


async def step_S5_validate(ctx: RunContext) -> None:
    """Runs concurrently with S4. Claims overlapping scope so the L2
    router fires a CONFLICT for one of them.
    """
    await asyncio.sleep(0.06)
    async with synapse.intend(
        scope=SCOPES["S5_validate_app"], agent="validator",
        session=ctx.session_id,
        expected_outcome="validate the application bundle",
    ) as i:
        t0 = time.monotonic()
        # Wait for drafter to populate cover_letters; bounded by drafter time
        for _ in range(80):
            if ctx.cover_letters:
                break
            await asyncio.sleep(0.05)
        ctx.validated = {
            "candidate": ctx.parsed_resume.get("name", "unknown"),
            "applications": [
                {"job_id": jid, "letter_bytes": len(letter),
                 "letter_first_line": letter.split("\n", 1)[0][:120]}
                for jid, letter in ctx.cover_letters.items()
            ],
            "validated_at": time.time(),
        }
        ctx.summary.steps.append(StepResult(
            step="S5_validate_app", role="validator",
            intention_id=i.intention_id, has_conflicts=i.has_conflicts,
            elapsed_s=round(time.monotonic() - t0, 2),
            output_bytes=len(json.dumps(ctx.validated))))


async def step_S6_submit(ctx: RunContext) -> None:
    async with synapse.intend(
        scope=SCOPES["S6_submit_apply"], agent="submitter",
        session=ctx.session_id,
        expected_outcome="submit applications via mock ATS",
    ) as i:
        t0 = time.monotonic()
        for jid, letter in ctx.cover_letters.items():
            job = next((j for j in ctx.all_jobs if j.id == jid), None)
            if job is None: continue
            res = await ctx.mock_submit(job, letter)
            ctx.submission_results.append(res)
        ctx.summary.steps.append(StepResult(
            step="S6_submit_apply", role="submitter",
            intention_id=i.intention_id, has_conflicts=i.has_conflicts,
            elapsed_s=round(time.monotonic() - t0, 2),
            output_bytes=len(json.dumps(ctx.submission_results))))


async def finalize(ctx: RunContext, pg_dsn: str, redis_url: str) -> None:
    from shared.runner_base import extract_envelope_log
    ctx.write_artifacts()
    await extract_envelope_log(ctx, pg_dsn, redis_url)
    ctx.save_summary()
