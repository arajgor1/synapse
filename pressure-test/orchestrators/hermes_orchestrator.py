"""Hermes orchestrator: Synapse-native — uses install_hermes_synapse_hooks
and wrap_tool_call_for_synapse directly (no third-party framework)."""
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


async def _s4_hermes_draft(ctx: RunContext) -> None:
    from synapse.bus import Bus
    from synapse.state import StateGraph
    from synapse.integrations.hermes_integration import (
        install_hermes_synapse_hooks, wrap_tool_call_for_synapse, clear_runtime,
    )

    async with synapse.intend(
        scope=SCOPES["S4_draft_letters"], agent="hermes_drafter",
        session=ctx.session_id,
        expected_outcome="draft 5 cover letters; record via Hermes hook",
    ) as i:
        t0 = time.monotonic()
        for jm in ctx.matched_roles[:5]:
            jid = jm.get("job_id") or jm.get("id") or ""
            job = next((j for j in ctx.all_jobs if j.id == jid), None)
            if job is None: continue
            ctx.cover_letters[jid] = await ctx.llm_draft_letter(job)

        # Hermes path: wrap each registration through the native synapse
        # tool-call hook (this is the synapse-native dispatch path).
        bus_url = os.environ.get("SYNAPSE_REDIS_URL", "redis://localhost:6379/0")
        pg_dsn = os.environ.get("SYNAPSE_POSTGRES_DSN",
                                "postgresql://synapse:synapse_dev@localhost:5432/synapse")
        bus = Bus(bus_url); state = StateGraph(pg_dsn)
        await bus.connect(); await state.connect()
        try:
            clear_runtime()
            await install_hermes_synapse_hooks(
                bus=bus, state=state, session_id=ctx.session_id,
                agent_id="hermes_drafter_inner", gate_ms=80,
            )
            for jid, letter in list(ctx.cover_letters.items())[:5]:
                async def actual_write():
                    return f"registered {jid}: {len(letter)}B"
                await wrap_tool_call_for_synapse(
                    "register_letter", {"job_id": jid, "letter_bytes": len(letter)},
                    actual_write, agent_id="hermes_drafter_inner",
                )
        finally:
            try: await bus.disconnect()
            except Exception: pass
            try: await state.disconnect()
            except Exception: pass

        ctx.summary.steps.append(StepResult(
            step="S4_draft_letters", role="hermes_drafter",
            intention_id=i.intention_id, has_conflicts=i.has_conflicts,
            elapsed_s=round(time.monotonic() - t0, 2),
            output_bytes=sum(len(v) for v in ctx.cover_letters.values())))


async def run(redis_url: str, pg_dsn: str, out_dir: Path) -> RunContext:
    ctx = RunContext("hermes", out_dir)
    await setup_session(ctx, "hermes", redis_url, pg_dsn)
    await step_S1_parse(ctx); await step_S2_match(ctx); await step_S3_scrub(ctx)
    await asyncio.gather(_s4_hermes_draft(ctx), step_S5_validate(ctx))
    await step_S6_submit(ctx)
    await finalize(ctx, pg_dsn, redis_url)
    return ctx
