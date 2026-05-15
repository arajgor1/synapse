"""Common runner helpers shared by all 11 framework-specific orchestrators.

Each orchestrator gets a `RunContext` with:
  - paths to write artifacts to
  - the resume + jobs already loaded
  - a synapse-installed session
  - helper methods that wrap the LLM calls (real OpenAI via
    `OPENAI_API_KEY`) and the scrub passes

The framework-specific code's job: decide HOW to dispatch the six steps
through THAT framework's agent abstraction.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import traceback
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List

from openai import AsyncOpenAI

from .jobs import Job, fetch_active_jobs
from .scrub import scrub, ScrubResult
from .spec import LLM_PROMPTS, PipelineSummary, SCOPES, StepResult


OPENAI_MODEL = os.environ.get("PRESSURE_TEST_MODEL", "gpt-4o-mini")


# ---------------------------------------------------------------------------
# RunContext: passed to every orchestrator
# ---------------------------------------------------------------------------
class RunContext:
    """Holds the per-framework run state. The orchestrator instantiates one,
    runs the six steps, then calls `.write_artifacts()` + `.save_summary()`.
    """

    def __init__(self, framework: str, out_dir: Path):
        self.framework = framework
        self.session_id = f"pressuretest_{framework}_{int(time.time())}"
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "cover_letters").mkdir(exist_ok=True)
        self.client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        self.summary = PipelineSummary(
            framework=framework,
            started_at=time.time(),
            finished_at=0.0,
            elapsed_s=0.0,
        )
        # The artifacts we accumulate as the pipeline runs
        self.resume_text: str = ""
        self.parsed_resume: Dict[str, Any] = {}
        self.all_jobs: List[Job] = []
        self.matched_roles: List[Dict[str, Any]] = []
        self.scrub_report: Dict[str, ScrubResult] = {}
        self.cover_letters: Dict[str, str] = {}
        self.validated: Dict[str, Any] = {}
        self.submission_results: List[Dict[str, Any]] = []

    # -----------------------------------------------------------------
    # LLM helpers (real calls)
    # -----------------------------------------------------------------
    async def llm_parse_resume(self) -> Dict[str, Any]:
        msg = LLM_PROMPTS["resume_parse"].format(resume=self.resume_text)
        r = await self.client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": msg}],
            response_format={"type": "json_object"},
            max_tokens=500,
        )
        return json.loads(r.choices[0].message.content)

    async def llm_match_roles(self) -> List[Dict[str, Any]]:
        jobs_str = "\n\n".join(
            f"[{j.id}] {j.title} @ {j.company} ({j.location})\n  {j.description[:300]}..."
            for j in self.all_jobs
        )
        msg = LLM_PROMPTS["role_match"].format(
            profile=json.dumps(self.parsed_resume, indent=2),
            jobs=jobs_str,
        )
        r = await self.client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": msg}],
            response_format={"type": "json_object"},
            max_tokens=600,
        )
        data = json.loads(r.choices[0].message.content)
        # Accept multiple JSON shapes
        if isinstance(data, dict):
            for k in ("matches", "top", "results", "roles"):
                if k in data and isinstance(data[k], list):
                    return data[k][:5]
            # bare dict — assume single object, wrap
            return [data]
        if isinstance(data, list):
            return data[:5]
        return []

    async def llm_draft_letter(self, job: Job) -> str:
        msg = LLM_PROMPTS["draft_letter"].format(
            profile=json.dumps(self.parsed_resume, indent=2),
            job=f"{job.title} @ {job.company}\n{job.description}",
        )
        r = await self.client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": msg}],
            max_tokens=400,
            temperature=0.3,
        )
        return r.choices[0].message.content.strip()

    # -----------------------------------------------------------------
    # Mock ATS submission (no real ToS exposure)
    # -----------------------------------------------------------------
    async def mock_submit(self, job: Job, cover_letter: str) -> Dict[str, Any]:
        # Simulate network latency + a deterministic-ish "submission".
        await asyncio.sleep(0.05)
        return {
            "job_id": job.id,
            "company": job.company,
            "title": job.title,
            "apply_url": job.apply_url,
            "ats": "mock_ats_v1",
            "submission_id": f"sub_{job.id}_{int(time.time() * 1000) % 100000}",
            "letter_bytes": len(cover_letter),
            "status": "submitted_mock",
        }

    # -----------------------------------------------------------------
    # Artifact writing
    # -----------------------------------------------------------------
    def write_artifacts(self) -> None:
        (self.out_dir / "resume_parsed.json").write_text(
            json.dumps(self.parsed_resume, indent=2), encoding="utf-8")
        (self.out_dir / "matched_roles.json").write_text(
            json.dumps(self.matched_roles, indent=2), encoding="utf-8")
        # scrub report
        scrub_dump = {
            jid: {
                "had_injection": s.had_injection,
                "detections": [
                    {"pattern": d.pattern, "severity": d.severity,
                     "span": list(d.span), "matched": d.matched}
                    for d in s.detections
                ],
                "fingerprints_replaced": s.fingerprints_replaced,
                "cleaned_text": s.cleaned_text,
            }
            for jid, s in self.scrub_report.items()
        }
        (self.out_dir / "scrub_report.json").write_text(
            json.dumps(scrub_dump, indent=2), encoding="utf-8")
        # cover letters
        for jid, letter in self.cover_letters.items():
            (self.out_dir / "cover_letters" / f"{jid}.md").write_text(
                letter, encoding="utf-8")
        # validated application
        (self.out_dir / "validated_application.json").write_text(
            json.dumps(self.validated, indent=2), encoding="utf-8")
        # submission results
        (self.out_dir / "submission_results.json").write_text(
            json.dumps(self.submission_results, indent=2), encoding="utf-8")

    def save_summary(self) -> None:
        self.summary.finished_at = time.time()
        self.summary.elapsed_s = self.summary.finished_at - self.summary.started_at
        (self.out_dir / "summary.json").write_text(
            json.dumps(self.summary.to_dict(), indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Audit-trail extraction: pull envelopes.jsonl + thought counts from PG/Redis
# ---------------------------------------------------------------------------
async def extract_envelope_log(ctx: RunContext, pg_dsn: str, redis_url: str) -> None:
    """Pull all INTENTION/RESOLUTION/CONFLICT envelopes for the session
    from Postgres, plus THOUGHT envelopes from Redis stream, write
    envelopes.jsonl into the run dir, and update the summary counters.
    """
    import asyncpg
    conn = await asyncpg.connect(pg_dsn)
    try:
        rows = await conn.fetch(
            "SELECT id, agent_id, session_id, scope, action, expected_outcome, "
            "       status, created_at, resolved_at "
            "FROM intentions WHERE session_id = $1 ORDER BY created_at",
            ctx.session_id,
        )
    finally:
        await conn.close()
    out_path = ctx.out_dir / "envelopes.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        intent_count = 0
        resolved = 0
        for r in rows:
            f.write(json.dumps({
                "type": "INTENTION",
                "id": r["id"],
                "agent_id": r["agent_id"],
                "session_id": r["session_id"],
                "scope": list(r["scope"] or []),
                "action": r["action"],
                "expected_outcome": r["expected_outcome"],
                "status": r["status"],
                "ts_ms": int((r["created_at"].timestamp()
                             if r["created_at"] else 0) * 1000),
            }, default=str) + "\n")
            intent_count += 1
            if r["status"] == "resolved":
                resolved += 1
        # THOUGHTs from Redis
        thought_count = 0
        conflict_count = 0
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(redis_url, decode_responses=True)
            stream = await r.xrange(
                f"synapse:session:{ctx.session_id}:events", count=500
            )
            for _eid, fields in stream:
                try:
                    e = json.loads(fields.get("e", "{}"))
                    if e.get("type") == "THOUGHT":
                        thought_count += 1
                        f.write(json.dumps(e, default=str) + "\n")
                    elif e.get("type") == "CONFLICT":
                        conflict_count += 1
                        f.write(json.dumps(e, default=str) + "\n")
                except Exception:
                    pass
            await r.aclose()
        except Exception:
            pass
    ctx.summary.intents_total = intent_count
    ctx.summary.intents_resolved = resolved
    ctx.summary.thoughts_total = thought_count
    ctx.summary.conflicts_total = conflict_count
