"""Realistic mid-stream injection test — proves the model BEHAVIOR changes,
not just that it verbally acknowledges the signal.

Three scenarios, each designed so a "real" continuation would commit to a
specific path AND a "post-inject" continuation must visibly diverge:

  A. Algorithmic pivot
     Pre:  "Write a Python function that sorts a list of integers."
     Inject (after model commits to a sort): "Constraint update — input is
       in range [0, 1000] and we need O(n) time. Switch algorithms."
     Pass condition: continuation writes counting/bucket sort (not the
       original quick/merge/Timsort) AND no longer uses .sort() / sorted().

  B. Tool-call plan pivot
     Pre:  "Output a JSON array of file edits to add token-bucket rate
       limiting in auth/middleware.ts."
     Inject (after model writes a few tool calls touching auth/middleware):
       "auth/middleware.ts is now scope-locked by another agent. Re-emit
       a plan that uses a NEW middleware file instead, e.g.
       auth/rate-limit-middleware.ts. Do not touch auth/middleware.ts."
     Pass condition: continuation contains the new path; never references
       the locked path.

  C. Multi-step plan pivot
     Pre:  "Write a 5-step plan to refactor a legacy auth flow. Use
       sequential numbered steps."
     Inject (after the model writes step 1 or 2): "Constraint: step 2
       (the database migration) must be skipped — that's owned by another
       team. Continue from where you are with step 2 omitted."
     Pass condition: the post-inject continuation does NOT include a
       database migration step.

For each (scenario, backend) pair we:
  1. Start a stream with the pre-inject prompt
  2. Read until we have ~120 chars of committed output
  3. Call inject_and_continue with the constraint update
  4. Read the continuation to completion
  5. Score the result with an LLM judge that returns structured JSON

Cost target: under $0.02 across 6 runs (Anthropic + OpenAI x 3 scenarios).

Run:
  ANTHROPIC_API_KEY=...  python examples/inject_realism_test.py --backend anthropic
  OPENAI_API_KEY=...     python examples/inject_realism_test.py --backend openai
  python examples/inject_realism_test.py --backend both
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_REPO_ROOT, "sdk-python"))
sys.path.insert(0, _REPO_ROOT)

from synapse.adapters.base import InferenceAdapter, StreamHandle  # noqa: E402


# ---------------------------------------------------------------------------
# Scenarios — each is (id, prompt, max_pre_tokens, injection, instruction,
# pass_check_prompt) — the pass_check_prompt asks an LLM judge to return JSON
# ---------------------------------------------------------------------------
@dataclass
class Scenario:
    id: str
    prompt: str
    pre_chars: int
    injection: str
    instruction: str
    judge_prompt: str  # Instructs the judge what to look for
    expected_pass_signals: list[str]  # Phrases that, if present in continuation,
    # strongly indicate behavior changed (used as a quick heuristic alongside the LLM judge)
    expected_fail_signals: list[str]  # Phrases that suggest no real pivot


SCENARIOS: list[Scenario] = [
    Scenario(
        id="A_algorithmic_pivot",
        prompt=(
            "Write a Python function that sorts a list of integers in ascending "
            "order. Include a brief docstring describing the algorithm you chose. "
            "Output complete, runnable Python."
        ),
        pre_chars=140,
        injection=(
            "Constraint update: the input is guaranteed to be in [0, 1000] "
            "and we need O(n) time. The previous algorithm cannot meet this. "
            "Switch to a non-comparison sort (counting sort or bucket sort)."
        ),
        instruction=(
            "Rewrite the function from scratch using the new constraint. "
            "Do not use sorted() or list.sort(). Show the full updated code."
        ),
        judge_prompt=(
            "You are a code reviewer. Read the model's continuation and decide:\n"
            "1. Did the continuation switch to a non-comparison sort algorithm "
            "(counting sort or bucket sort)?\n"
            "2. Did it AVOID using sorted() or .sort()?\n"
            "Return strict JSON: "
            '{"switched_algorithm": true|false, "uses_builtin_sort": true|false, '
            '"verdict": "PASS"|"FAIL", "reason": "..."}'
        ),
        expected_pass_signals=["counting", "bucket", "count = ", "buckets ="],
        expected_fail_signals=["sorted(", ".sort(", "merge sort", "quicksort"],
    ),
    Scenario(
        id="B_tool_call_pivot",
        prompt=(
            "Output a JSON array of 3 file edits that add token-bucket rate "
            "limiting to an Express.js app. Each edit should be of the form: "
            '{"path": "...", "action": "create|modify|delete", "summary": "..."}. '
            "The rate limiter goes in auth/middleware.ts. "
            "Output ONLY the JSON array, no prose."
        ),
        pre_chars=120,
        injection=(
            "SCOPE LOCK: auth/middleware.ts is currently being modified by "
            "another agent (agent_b). You must not touch it. Re-emit your plan "
            "but route the rate limiter into a NEW file at "
            "auth/rate-limit-middleware.ts so it doesn't collide."
        ),
        instruction=(
            "Output a fresh JSON array with the new path. Do NOT reference "
            "auth/middleware.ts in any of the edits."
        ),
        judge_prompt=(
            "You are inspecting a JSON file-edit plan emitted by an LLM agent.\n"
            "1. Did the continuation reference auth/rate-limit-middleware.ts?\n"
            "2. Did it AVOID referencing auth/middleware.ts?\n"
            "Return strict JSON: "
            '{"used_new_path": true|false, "still_uses_locked_path": true|false, '
            '"verdict": "PASS"|"FAIL", "reason": "..."}'
        ),
        expected_pass_signals=["auth/rate-limit-middleware.ts"],
        expected_fail_signals=[],  # presence of locked path = fail; checked by judge
    ),
    Scenario(
        id="C_multi_step_pivot",
        prompt=(
            "Write a 5-step plan to refactor a legacy auth flow. Use sequential "
            "numbered steps (1., 2., 3., 4., 5.). Each step on its own line, "
            "ONE sentence per step. Step 1 is database migration."
        ),
        pre_chars=80,
        injection=(
            "Constraint: the database migration step must be SKIPPED — that's "
            "owned by another team and they will handle it independently. "
            "Continue your plan but ensure the database migration is omitted."
        ),
        instruction=(
            "Re-emit the full numbered plan with the database migration step removed. "
            "Renumber the remaining steps."
        ),
        # MECHANICAL judge: did the continuation follow the instruction or not?
        # Do NOT evaluate whether following the instruction was a good idea.
        judge_prompt=(
            "You are a mechanical compliance checker, NOT a quality reviewer.\n"
            "Your ONLY task: did the continuation follow the explicit instruction "
            "to OMIT the database migration step?\n\n"
            "PASS if any of these are true:\n"
            "  - The continuation has zero references to database migration, "
            "schema migration, ALTER TABLE, or data layer migration\n"
            "  - The continuation explicitly notes that db migration is "
            "owned by another team and intentionally skips it\n\n"
            "FAIL only if the continuation still includes a database migration step.\n\n"
            "DO NOT evaluate plan quality, completeness, or whether skipping db "
            "migration is wise. Only evaluate compliance with the omission instruction.\n\n"
            'Return strict JSON: {"omits_db_migration": true|false, '
            '"verdict": "PASS"|"FAIL", "reason": "..."}'
        ),
        expected_pass_signals=[],
        expected_fail_signals=["database migration", "schema migration", "alter table"],
    ),
]


# ---------------------------------------------------------------------------
@dataclass
class Result:
    scenario_id: str
    backend: str
    model_id: str
    pre_inject_text: str
    continuation: str
    heuristic_pass_signals_hit: list[str]
    heuristic_fail_signals_hit: list[str]
    judge_json: dict[str, Any] = field(default_factory=dict)
    elapsed_seconds: float = 0.0
    pass_overall: bool = False


# ---------------------------------------------------------------------------
def make_backend(name: str) -> InferenceAdapter:
    if name == "anthropic":
        from synapse.adapters.hosted import AnthropicAdapter
        return AnthropicAdapter(model="claude-haiku-4-5-20251001", max_tokens=400)
    if name == "openai":
        from synapse.adapters.hosted import OpenAIAdapter
        return OpenAIAdapter(model="gpt-4o-mini", max_tokens=400)
    raise ValueError(f"unknown backend: {name}")


async def _read_until_chars(
    adapter: InferenceAdapter, handle: StreamHandle, target_chars: int
) -> str:
    text = ""
    async for tok in adapter.read_tokens(handle):
        text += tok.text
        if len(text) >= target_chars:
            break
    return text


async def _read_to_completion(adapter: InferenceAdapter, handle: StreamHandle) -> str:
    text = ""
    async for tok in adapter.read_tokens(handle):
        text += tok.text
    return text


async def _llm_judge(
    adapter: InferenceAdapter, judge_prompt: str, continuation: str
) -> dict[str, Any]:
    """Use the same backend as a judge. Strict JSON request."""
    full_prompt = (
        f"{judge_prompt}\n\n"
        f"Model's continuation:\n---\n{continuation}\n---\n\n"
        f"Output only the JSON object with no markdown fences or prose."
    )
    handle = await adapter.start_stream(
        messages=[{"role": "user", "content": full_prompt}],
        params={"max_tokens": 200, "temperature": 0.0},
    )
    text = ""
    async for tok in adapter.read_tokens(handle):
        text += tok.text
    text = text.strip()
    # Extract JSON if wrapped in fences
    if "```" in text:
        for part in text.split("```"):
            p = part.lstrip("json").strip()
            if p.startswith("{"):
                text = p
                break
    if "{" in text and "}" in text:
        text = text[text.find("{") : text.rfind("}") + 1]
    try:
        return json.loads(text)
    except Exception as e:
        return {"verdict": "FAIL", "reason": f"unparseable judge output: {e!r}", "raw": text[:300]}


async def run_scenario(adapter: InferenceAdapter, sc: Scenario, backend_name: str) -> Result:
    started = time.time()
    handle = await adapter.start_stream(
        messages=[{"role": "user", "content": sc.prompt}],
        params={"max_tokens": 400, "temperature": 0.0},
    )
    pre = await _read_until_chars(adapter, handle, sc.pre_chars)

    # Inject mid-stream
    new_handle = await adapter.inject_and_continue(
        handle, injection=sc.injection, instruction=sc.instruction
    )
    cont = await _read_to_completion(adapter, new_handle)

    elapsed = time.time() - started

    cont_lower = cont.lower()
    pass_signals = [s for s in sc.expected_pass_signals if s.lower() in cont_lower]
    fail_signals = [s for s in sc.expected_fail_signals if s.lower() in cont_lower]

    judge = await _llm_judge(adapter, sc.judge_prompt, cont)
    pass_overall = (judge.get("verdict") == "PASS") and (not fail_signals)

    return Result(
        scenario_id=sc.id,
        backend=backend_name,
        model_id=adapter.capabilities.model_id or "?",
        pre_inject_text=pre[:300],
        continuation=cont[:1200],
        heuristic_pass_signals_hit=pass_signals,
        heuristic_fail_signals_hit=fail_signals,
        judge_json=judge,
        elapsed_seconds=round(elapsed, 2),
        pass_overall=pass_overall,
    )


def _print_summary(rs: list[Result]) -> None:
    print("\n" + "=" * 78)
    print(f"  {'scenario':<22} {'backend':<10} {'model':<32} {'verdict'}")
    print("-" * 78)
    for r in rs:
        v = "PASS" if r.pass_overall else "FAIL"
        flag = "✓" if r.pass_overall else "✗"
        print(f"  {r.scenario_id:<22} {r.backend:<10} {r.model_id:<32} {flag} {v}")
    passed = sum(1 for r in rs if r.pass_overall)
    print(f"\n  Total: {passed} / {len(rs)} passed")
    print("=" * 78)


def _save_results(rs: list[Result], out_dir: str = "bench/results") -> str:
    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    out_path = os.path.join(out_dir, f"inject_realism_{ts}.json")
    with open(out_path, "w") as f:
        json.dump([asdict(r) for r in rs], f, indent=2)
    return out_path


async def main(backends: list[str]) -> int:
    all_results: list[Result] = []
    for bname in backends:
        try:
            adapter = make_backend(bname)
        except Exception as e:
            print(f"[skip] {bname}: {e}")
            continue
        for sc in SCENARIOS:
            print(f"\nRunning {sc.id} on {bname}...")
            try:
                r = await run_scenario(adapter, sc, bname)
                all_results.append(r)
                judge = r.judge_json
                jverdict = judge.get("verdict", "?")
                jreason = (judge.get("reason") or "")[:150]
                pass_sig = r.heuristic_pass_signals_hit
                fail_sig = r.heuristic_fail_signals_hit
                print(f"  judge: {jverdict} — {jreason}")
                if pass_sig:
                    print(f"  pass-signals hit:    {pass_sig}")
                if fail_sig:
                    print(f"  fail-signals hit:    {fail_sig}")
                print(f"  pre-inject (first 100 chars): {r.pre_inject_text[:100]!r}")
                print(f"  continuation start:           {r.continuation[:120]!r}")
                print(f"  overall: {'PASS' if r.pass_overall else 'FAIL'}")
            except Exception as e:
                print(f"  ERROR: {e}")
                all_results.append(
                    Result(
                        scenario_id=sc.id, backend=bname, model_id="ERROR",
                        pre_inject_text="", continuation="",
                        heuristic_pass_signals_hit=[], heuristic_fail_signals_hit=[],
                        judge_json={"error": str(e)},
                    )
                )
    _print_summary(all_results)
    out = _save_results(all_results)
    print(f"\nResults saved -> {out}")
    return 0 if all(r.pass_overall for r in all_results) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backend",
        choices=["anthropic", "openai", "both"],
        default="both",
    )
    args = parser.parse_args()
    backends = ["anthropic", "openai"] if args.backend == "both" else [args.backend]
    sys.exit(asyncio.run(main(backends)))
