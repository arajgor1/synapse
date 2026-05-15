"""The pressure-test workload spec.

Every framework-specific orchestrator implements `run_pipeline()` from
this contract. The orchestrator is responsible for **how** the agents
talk to each other (sequential, ReAct, supervisor-worker, etc.) — that
choice is the framework-specific bit being tested.

The pipeline has six steps:

  step              role             produces
  ----              ----             --------
  S1  resume_parse  Parser           structured resume dict
  S2  role_match    Matcher          ranked-top-5 jobs (filtered ≤72h, scrub-cleaned)
  S3  scrub_jobs    Scrubber         per-job (cleaned_desc, detections)
  S4  draft_letters Drafter          cover letter per role (real LLM call)
  S5  validate_app  Validator        schema-checked application bundle
  S6  submit_apply  Submitter        mock-ATS submission with synapse INTENT

Each step:
  - fires a synapse.intend() with scope = "pressuretest.{step}:w"
  - may emit a CONFLICT envelope if two agents target the same role (we
    intentionally have the Drafter and Validator briefly compete on
    role-3's scope to exercise the L2 router)
  - records the produced artifact on disk for the audit bundle

Output artifact bundle:
  runs/{framework}/
    envelopes.jsonl
    resume_parsed.json
    matched_roles.json
    scrub_report.json
    cover_letters/
      job_001.md
      ...
    validated_application.json
    submission_results.json
    summary.json
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

# 11 frameworks under test.
FRAMEWORKS = [
    "autogen",
    "crewai",
    "langgraph",
    "smolagents",
    "agno",
    "llama_index",
    "pydantic_ai",
    "openai_agents",
    "google_adk",
    "hermes",
    "openclaw",  # TypeScript — runs differently
]


@dataclass
class StepResult:
    step: str
    role: str
    intention_id: str
    has_conflicts: bool
    elapsed_s: float
    output_bytes: int
    error: str = ""


@dataclass
class PipelineSummary:
    framework: str
    started_at: float
    finished_at: float
    elapsed_s: float
    steps: List[StepResult] = field(default_factory=list)
    intents_total: int = 0
    intents_resolved: int = 0
    conflicts_total: int = 0
    thoughts_total: int = 0
    injections_detected: int = 0
    fingerprints_laundered: int = 0
    final_artifact_paths: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "steps": [asdict(s) for s in self.steps],
        }


# Step-to-scope mapping. The orchestrator passes these to
# synapse.intend(scope=...) so the audit trail records which agent
# claimed which step.
SCOPES = {
    "S1_resume_parse":   ["pressuretest.parse:w", "pressuretest.resume:r"],
    "S2_role_match":     ["pressuretest.match:w", "pressuretest.jobs:r"],
    "S3_scrub_jobs":     ["pressuretest.scrub:w"],
    "S4_draft_letters":  ["pressuretest.draft:w", "pressuretest.letter_role3:w"],
    # S5 intentionally targets the same letter_role3 scope as S4 to exercise
    # the L2 router. The orchestrator should run them as overlapping
    # intents so the conflict surfaces.
    "S5_validate_app":   ["pressuretest.validate:w", "pressuretest.letter_role3:r"],
    "S6_submit_apply":   ["pressuretest.submit:w"],
}

LLM_PROMPTS = {
    "resume_parse": (
        "Extract the structured resume from the text below. Output STRICT JSON "
        "with keys: name, email, years_experience, skills (list of strings), "
        "current_role, current_company, summary (≤2 sentences). Output ONLY "
        "the JSON, no prose, no markdown fences.\n\nResume:\n{resume}"
    ),
    "role_match": (
        "You are a recruiter. Given the candidate profile and 8 active job "
        "postings, rank the top 5 best fits in order of strength. Output "
        "STRICT JSON: a list of objects with keys job_id and reason "
        "(1 sentence why it fits). Output ONLY the JSON.\n\n"
        "Candidate:\n{profile}\n\nJobs:\n{jobs}"
    ),
    "draft_letter": (
        "Write a focused 4-paragraph cover letter (≤200 words) for the "
        "candidate applying to this role. Tone: professional, no superlatives, "
        "concrete examples from the resume. Output ONLY the body of the "
        "letter, no header/footer/signature.\n\n"
        "Candidate:\n{profile}\n\nRole:\n{job}"
    ),
}
