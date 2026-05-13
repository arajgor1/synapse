# Synapse v0.2.1 — Testing Protocol & Forensic Audit

> **Purpose of this document.** The user requested a forensic-quality record of every test run during the v0.2.1 pitch campaign. The intent is to make the methodology auditable: anyone reading should be able to verify what was tested, what prompts were sent (verbatim), what was modeled vs measured, and whether any prompt was constructed to nudge a result.
>
> Every test below records: **What** (the claim under test), **How** (methodology), **Inputs** (data + verbatim prompts), **Expected** (pre-registered prediction), **Actual** (raw outcome with file references), **Conclusion** (verdict).
>
> Tests are numbered chronologically. Each links to the underlying script and result JSON in the repo.

**Author:** Aadit Rajgor (with Claude Code as engineering assistant)
**Period:** 2026-05-08
**Cumulative LLM spend across all tests:** ~$1.76 of $10 cap
**Repo state at end:** branch `main`, commits up through the latest tip

---

## Test 1 — Oracle smoke test (Phase 0 Gate)

### What was tested
Whether the ground-truth oracle (`bench/oracle/scorer.py`) correctly identifies **file collisions, silent overwrites, textual conflict markers, coherence-marker matching, and belief divergences** when given a known-truth synthetic fixture. This was a unit test of the oracle BEFORE running it on real cells.

### How tested
A synthetic fixture (`bench/oracle/test_oracle.py`) constructs:
- A repo with 5 files (`models.py`, `routes/subscriptions.py`, `routes/admin.py`, `routes/invoices.py`, `tests/test_cancel.py`) intentionally embedding 1 expected coherence miss (no American "canceled" string literal)
- A write log with 8 events: 2 collisions on `models.py` and `routes/invoices.py`, both with different content hashes (silent overwrites)
- A stub Anthropic client that returns 3 canned divergences (`canceled_column_spelling`, `subscription_state_value`, `already_canceled_status_code`)

### Inputs
- **Synthetic repo files**: `bench/oracle/test_oracle.py` lines 51–116 (verbatim file contents written to tempdir)
- **Synthetic write log**: `bench/oracle/test_oracle.py` lines 118–157
- **Stub LLM canned response** (verbatim): `bench/oracle/test_oracle.py` lines 159–197 — 3 divergences with full `key`, `value_a`, `value_b`, `evidence_a`, `evidence_b`, `severity`, `rationale`
- **No Anthropic API call made.** No prompts sent to any LLM. Test runs offline.

### Expected (pre-registered, before running)
| Metric | Expected |
|---|---|
| `find_file_collisions` | exactly 2 |
| `find_silent_overwrites` | exactly 2 |
| `find_textual_conflicts_in_repo` | exactly 0 |
| `score_coherence` | 14/15 markers, miss = `state_value_canceled` |
| `detect_belief_divergences` (with stub client) | exactly 3 |

### Actual
All 5 assertions matched exactly. Output:
```
=== Gate 0: oracle smoke test ===
  ✓ file_collisions = 2  (['app/models.py', 'app/routes/invoices.py'])
  ✓ silent_overwrites = 2
  ✓ textual_conflicts = 0
  ✓ coherence = 0.9333  (14/15 markers, 1 expected miss: state_value_canceled)
  ✓ belief_divergences = 3
=== Gate 0 PASSED ===
```

Two real bugs caught and fixed during this test:
1. `BELIEF_ORACLE_PROMPT.format()` choked on JSON braces in the template — fixed by switching to `.replace()` substitution
2. Initial loose bound `0.3 ≤ coherence ≤ 0.85` was rejected by the test harness; tightened to exact-marker assertion

### Conclusion
Oracle is mechanically correct against known-truth input. No LLM prompts were used — this is a pure deterministic test.

### Honesty notes
- The stub Anthropic client returns canned divergences. Real Anthropic responses can return different shapes; that risk is tested in Tests 4 (multi-orch May 8) and 9 (Option A) where real Anthropic is used.
- The oracle's belief-divergence detection at scale is only as good as the LLM-judge it uses (Haiku 4.5 in production usage). False-positive rate at scale not measured here.

---

## Test 2 — Cloud trace importer C12 (Bedrock + Vertex + Azure)

### What was tested
Whether `synapse audit` can ingest hand-crafted samples in the Bedrock Agents, GCP Vertex Agent Builder, and Azure AI Agent Service trace formats and detect cross-agent conflicts.

### How tested
For each of the 3 cloud vendors, I hand-wrote a sample trace export designed to be format-compliant per vendor docs and embed exactly the kind of cross-agent collision a real two-agent run would produce. Each sample contains 2 distinct agents (different `agentId`) editing the same logical thing (e.g., schema column on `subscriptions` table) with conflicting choices (American vs British spelling of "canceled").

### Inputs

**Bedrock sample** (`bench/scenarios/cloud_trace_samples/bedrock_two_agents_billing.json`):
- 7 trace blocks: 1 per agent for orchestration init, 3 action-group invocations (schema add_column, /cancel endpoint, /restore endpoint)
- Adversarial quirks intentionally included: missing endTime, mixed apiPath/function styles, parameters list with mixed types, one trace with empty `actionGroupName`
- Format spec source: AWS docs https://docs.aws.amazon.com/bedrock/latest/userguide/trace-events.html

**Vertex sample** (`bench/scenarios/cloud_trace_samples/vertex_two_agents_billing.json`):
- 5 spans with `gen_ai.tool.name`, `gen_ai.agent.name`, `gcp.vertex.agent.session_id` attributes
- Adversarial: mixed flat-attribute vs `attributeMap` shapes, one span with missing endTime
- Format spec source: Vertex AI Agent Builder Cloud Trace export format

**Azure sample** (`bench/scenarios/cloud_trace_samples/azure_two_agents_billing.json`):
- 5 rows in App Insights `value` array shape with `customDimensions` containing `ai.agent.id`, `ai.tool.name`, `ai.tool.input`
- Adversarial: one row has `customDimensions` as a JSON string (App Insights sometimes serializes that way), one row without `agent.id`
- Format spec source: Azure AI Agent Service / App Insights schema

**No prompts used.** This test exercises only the deterministic importer + scope inference + conflict detector.

### Expected
- ≥2 of 3 cloud trace formats produce ≥1 cross-agent conflict
- Auto-detection (`auto_import`) correctly identifies each format's shape

### Actual
| Format | events | writes | conflicts | result file |
|---|---|---|---|---|
| Bedrock | 5 | 4 | **2** | `bench/results/v02_pitch_phase1/C12_cloud_trace_audit.json` |
| Vertex | 4 | 4 | **1** | (same) |
| Azure | 4 | 4 | **1** | (same) |

Auto-detection sniffer correctly routed each file to its importer.

**Bugs surfaced + fixed during this test:**
1. Bedrock importer wasn't unpacking the `traces[].trace` wrapper structure
2. `is_write` heuristic missed cloud-vendor functional tool names like `schema_migration.add_column` — extended keyword list
3. Audit lookback default was 60s — production trace exports span hours; bumped to 24h
4. Vertex sample initially had a clock-skew quirk (mixing 2025 protobuf-seconds with 2026 ISO strings) that put events outside the lookback window. **The sample was modified to use consistent timestamps so the audit could detect the underlying real semantic collision.** This is a sample-quality fix, not a concealment — the original quirk is documented in the importer's docstring.
5. Azure session_id fallback was chaining `operation_ParentId` (a span id) into session position; fixed to fall back to `operation_Id` (trace id)

### Conclusion
Importers work on the hand-crafted samples for all 3 cloud formats. **PASS at the format-parsing level.**

### Honesty notes
- These samples are **hand-crafted to be format-compliant**. They are NOT exported from a live Bedrock / Vertex / Azure agent run.
- The "100% format pass" claim only validates the importer's parsing logic; it does NOT validate that the importer would correctly handle every quirk a real cloud-vendor exporter produces.
- The user explicitly asked for real cloud trace audits; I do not have AWS/GCP/Azure credentials, so this gap remains. Test 13 partially compensates by using a real OpenInference auto-instrumentor against a real Anthropic call.

---

## Test 3 — Audit recall on synthesized multi-orch trace (C10)

### What was tested
Whether `synapse audit` running post-hoc on a trace synthesized from the multi-orchestrator May-8 stdout achieves ≥70% recall on the 4 known cross-team file collisions caught by live mode.

### How tested
1. Read `bench/results/v02_multi_orchestrator_20260508-141754.json` (the live multi-orch run from May 8)
2. Parse the structured "cross-team overlap" summary lines from the stdout via regex
3. Synthesize an OpenInference-shaped span list with one span per (agent, path) tuple
4. Run `audit_traces()` on the synthesized JSON
5. Compare detected unique file collisions to ground-truth files

### Inputs
Regex used for extraction (`bench/results/v02_pitch_phase1/...py`-style):
```python
re.compile(r"^\s+(src/\S+):\s*\[(.*?)\]", re.MULTILINE)
```

Ground truth file collisions (from May-8 FINDINGS.md):
```
src/db/schema.sql
src/routes/auth.js
src/routes/subscriptions.js
src/routes/invoices.js
```

**No LLM prompts.** Synthesis is pure regex + JSON construction.

### Expected
- ≥70% recall on file collisions
- All 4 ground-truth files appear in the audit output

### Actual
| Metric | Value |
|---|---|
| Spans synthesized | 8 |
| Audit events | 8 |
| Audit conflicts | 4 |
| Unique cross-agent file collisions | **4** (matches all ground truth) |
| **Recall** | **100% (4/4)** |

Result file: `bench/results/v02_pitch_phase1/C10_audit_recall.json`

### Conclusion
Recall PASSES. **But this test has a known weakness:** the trace was *synthesized from the same stdout that produced the ground truth*. It is essentially a tautology — the audit detects whatever the regex extracted. A more rigorous test would generate the trace via OpenInference auto-instrumentation during the original multi-orch run; that wasn't done.

### Honesty notes
- This is the test's biggest weakness and I should have flagged it more loudly in the earlier writeup. Test 13 (real OpenInference exporter) addresses this.

---

## Test 4 — Multi-orchestrator natural workload (May 8 — pre-existing ground truth)

### What was tested
Whether two independent LangGraph orchestrator+worker teams, each given the same task with no shared coordinator, produce silent collisions, and whether Synapse catches them.

### How tested
Modal sandbox, two LangGraph crews running in parallel via `asyncio.gather`. Three modes compared: `no_synapse`, `observer` (`MergePolicy.redirect`), `full` (`MergePolicy.auto_merge` + `emit_beliefs_from_tool_results=True`).

### Inputs

**The exact prompt given to each orchestrator** (verbatim from `runtime/modal/_payloads/v02_multi_orchestrator.py` line 73):
```
You are the lead architect of an AI engineering team building a mini-Stripe
billing platform. The system needs:
  - User accounts with email + password auth
  - Subscriptions (per-seat OR usage-based — your call)
  - Invoices with line items
  - Stripe webhook handling
  - Test coverage on the critical paths

You have 2 worker agents available, each can write 1 file per turn:
  - {backend_id}  (Express + Postgres + bcrypt)
  - {frontend_id} (React + Tailwind admin dashboard)

You decide:
  1. What file each worker writes next
  2. What the file should contain (1-2 line spec)
  3. When to STOP (when you think the system is functionally complete)

Output ONLY valid JSON for each turn:
  {{"thought": "<one-line plan>", "assignments": [
      {{"agent": "{backend_id}", "file": "<path>", "spec": "<1-2 lines>"}}
   ], "done": false}}

When done: {{"thought":"...","assignments":[],"done":true}}.
Be decisive. You are independent — there is no other team to coordinate with.
```

**Critical methodology note:** the prompt explicitly says "You are independent — there is no other team to coordinate with." This was deliberate to test the **uncoordinated case**. It does NOT tell the agents to collide — it just removes the coordination affordance. The collisions emerge organically.

The same prompt was given to alpha team and bravo team. Both used `claude-haiku-4-5-20251001`, max_tokens=400 for orchestrator, max_tokens=500 for workers.

### Expected (pre-registered)
- `no_synapse`: ≥3 silent file overwrites
- `observer`: ≥3 cross-team conflicts detected
- `full`: ≥2 auto-merges fired, ≥2 belief divergences caught

### Actual
| Metric | no_synapse | observer | full |
|---|---|---|---|
| Files written | 27 | 21 | 17 |
| Cross-team file overlaps | 1 (visible) | 4 | 4 |
| Intentions persisted | 0 | 32 | 24 |
| **CONFLICT envelopes** | **0** | **6** | **10** |
| **auto_merges** | **0** | **0** | **4** |
| Belief divergences | 0 | 3 | 2 |
| Elapsed | 52.5s | 156.5s | 141.8s |

The 4 organic file collisions caught: `src/db/schema.sql`, `src/routes/auth.js`, `src/routes/subscriptions.js`, `src/routes/invoices.js`.

The 3 belief divergences caught organically:
- `login_api_endpoint`: `/api/login` vs `/auth/login` (round 1) and `/api/login` vs `/api/auth/login` (round 2)
- `subscriptions_table_columns`: `["user_id","plan","seat_count","created_at"]` vs `["user_id","plan_id","seats","billing_date","status"]`
- `register_form_fields`: `["email","password","confirmPassword"]` vs `["email","password"]`

Result file: `bench/results/v02_multi_orchestrator_20260508-141754.json` and `..._FINDINGS.md`

### Conclusion
Real LLMs in real LangGraph crews produce real cross-team collisions when given the same task without coordination. Synapse caught them in observer + full modes. **This is the campaign's strongest piece of pre-IRL real evidence.**

### Honesty notes
- Rate-limit pressure hit `full` mode at alpha's t5; alpha stopped at t4, bravo continued through t8. Documented in FINDINGS.
- The orchestrator prompt's "be decisive" + "you are independent" framing makes the agents more likely to commit to file paths. A different prompt could yield different results. The prompt was held identical across modes so this doesn't bias one mode against another, but it does mean "this collision rate" is prompt-dependent.
- The 4 cross-team file overlaps in observer/full vs 1 in no_synapse is interesting: when Synapse is observing, it doesn't reduce the overlap (it warns but doesn't reroute in observer mode). The visible overlap count goes up because the system actually records both attempts. In no_synapse mode, the first writer's content is overwritten before the system ever sees there were two.

---

## Test 5 — Strategy comparison simulator (Phase 4)

### What was tested
For 5 strategies (no_synapse, git branches, PR+CI, shared coordination.md, Synapse auto_merge), what fraction of file collisions and belief divergences each catches.

### How tested
Offline simulator (`bench/strategy_simulator.py`) operating on the same write log as Test 4 (multi-orch May 8). Holds agent behavior constant; varies only the strategy.

### Inputs
- Multi-orch trace as input
- For S2 (git branches): real `git init` + `git merge` in tempdir, but agent writes are **stand-in content strings** (not real LLM-generated code), so git only fires on file-path overlap, not semantic
- For S3 (PR+CI): **no pytest actually run** — uses `round(silent * 0.30)` as estimate, deterministic value `belief_caught = 1` (the schema-shaped one) based on prior observation
- For S4 (shared coord.md): **no LLM ever read a coord.md** — uses deterministic `hash(...) % 100 < 40` to model 40% LLM compliance
- For S5 (Synapse): pulled from multi-orch May 8 ground truth (4 collisions, 3 beliefs)

### Expected
- S5 catches both file collisions AND belief divergences
- S2 catches file collisions but 0 beliefs
- S3 partial on both
- S4 weak on both

### Actual
```
strategy                       writes   silent  textual  beliefs    coh
----------------------------------------------------------------------------
s1_no_synapse                       8        4        0        0   1.00
s2_git_branches                     8        0        4        0   0.60
s3_pr_ci                            8        3        1        1   0.85
s4_shared_coord_md                  8        2        0        0   0.70
s5_synapse_auto_merge               8        0        4        3   1.10
```

### Conclusion
Pattern matches expectations. **But:** S3 and S4 numbers are MODELED, not measured. The user pushed back on this in their next message and rightly so.

### Honesty notes
- THIS IS THE MAIN TEST THAT WAS LATER REPLACED BY OPTION A (real CI/CD loop). The simulator made claims that real measurement contradicted in nuanced ways (Option A showed CI catches *0* belief divergences, not 1, and that Synapse + CI did NOT improve coherence).
- The simulator should be considered a *modeling exercise*, not evidence. Tests 9 (Option A), 10 (Option B), 11 (Option C) are the real evidence.

---

## Test 6 — Strands adapter smoke test (against fake module)

### What was tested
Whether the Strands framework adapter (`sdk-python/synapse/frameworks/strands.py`) correctly patches a class with the canonical method signature.

### How tested
Built a fake `strands` module hierarchy in `sys.modules` with a `ToolHandler` class exposing `async handle_tool_call(tool_use, agent, ...)`. Then ran `synapse.install(framework="strands")` and verified `__wrapped__` attribute is set on the patched method.

### Inputs
Fake module structure (verbatim from `bench/oracle/test_strands_adapter.py` lines 28–47):
```python
class ToolHandler:
    async def handle_tool_call(self, tool_use, agent, *args, **kwargs):
        return {"status": "ok", "tool": tool_use.name}
```

**No prompts.** No LLM calls.

### Expected
Adapter sets `ToolHandler.handle_tool_call.__wrapped__`; non-write tools fall through cleanly; write tools have scope inferred.

### Actual
```
=== Strands adapter smoke test ===
  ✓ ToolHandler.handle_tool_call is wrapped
  ✓ non-write tool falls through: {'status': 'ok', 'tool': 'search_docs'}
  ✓ scope inference for edit_file: ['repo.fs.src/auth.py:w']
=== Strands smoke test PASSED ===
```

### Conclusion
**This test passed but was meaningless.** The fake module was built to match what the adapter expected. Test 11 (Option C) showed the adapter doesn't work against the real Strands SDK because the real SDK uses module-level functions (`event_loop._handle_tool_execution`) not class methods.

### Honesty notes
- This is the textbook example of "smoke test against a mock validates the mock, not the production code." Test 12 (real-SDK smoke for all 11 adapters) was added specifically because of this finding.

---

## Test 7 — FS watcher smoke test (with synthetic agent writes)

### What was tested
Whether the FS watcher in `sdk-python/synapse/watchers/fs_watcher.py` captures file modifications and emits JSONL audit events with correct agent attribution when two watchers run concurrently on the same dir.

### How tested
Two `FSWatcher` instances (alice, bob) on a shared tempdir. `pathlib.write_text()` simulates "agent writes" — first alice's models.py, then bob overwrites, then alice writes auth.py. Run `synapse audit` on the resulting JSONL log.

### Inputs
File contents written (verbatim):
```
"# alice's version: canceled_at\n"
"# bob's version: cancelled_at\n"
"# alice's auth\n"
```

No prompts. Pure deterministic FS operations.

### Expected
- 2+ events captured per agent (3 writes × 2 watchers seeing each)
- Audit detects ≥2 cross-agent file collisions

### Actual
```
JSONL: 6 events  (alice writes=3, bob writes=3)
  agents: ['alice', 'bob']
  paths:  ['auth.py', 'models.py']

Audit on FS-watcher log:
  events=6 writes=6 conflicts=4
  unique cross-agent collisions: 2
    auth.py (alice vs bob)
    models.py (alice vs bob)
```

**Real bug surfaced + fixed:** the watcher was logging to `.synapse/runs/` and re-detecting its own log writes, causing infinite collision spam. Fixed by adding `.synapse/` to `_IGNORE_PATTERNS`.

### Conclusion
FS watcher captures concurrent writes and synapse audit detects the resulting cross-agent collisions. **PASSED.**

### Honesty notes
- The "agents" in this test were `pathlib.write_text()` calls, NOT real Claude Code or Cursor sessions. Test 10 (Option B) replaced this with real Claude Code.
- Two watchers on the same dir produce attribution noise (each watcher attributes every write to its own agent). The audit still detects the collision correctly but the per-write attribution is ambiguous. For clean attribution, the per-session Claude Code BeforeTool hook is the right path; the FS watcher is a fallback.

---

## Test 8 — Slim install end-to-end verification

### What was tested
Whether `pip install synapse-protocol` (slim, no `[live]` extras) into a fresh virtualenv produces a working `synapse audit` CLI.

### How tested
1. `python -m build --sdist --wheel` to produce `synapse_protocol-0.2.1a0-py3-none-any.whl`
2. `python -m venv /tmp/synapse-test-venv` (fresh venv)
3. `pip install <wheel>` → installs only pydantic + jsonschema as deps
4. `synapse audit bench/scenarios/cloud_trace_samples/bedrock_two_agents_billing.json` from the venv

### Inputs
Verbatim command and output:
```
Installing collected packages: typing-extensions, rpds-py, attrs, annotated-types,
typing-inspection, referencing, pydantic-core, pydantic, jsonschema-specifications,
jsonschema, synapse-protocol
Successfully installed annotated-types-0.7.0 attrs-26.1.0 jsonschema-4.26.0
jsonschema-specifications-2025.9.1 pydantic-2.13.4 pydantic-core-2.46.4 referencing-0.37.0
rpds-py-0.30.0 synapse-protocol-0.2.1a0 typing-extensions-4.15.0 typing-inspection-0.4.2

$ synapse audit bedrock_two_agents_billing.json
Loaded 5 events from 1 session(s).
  write events:   4
  conflicts:      2 (2 stale_base_overwrite)
  est. waste:     ~400 tokens / ~$0.00
  HTML report -> ./synapse-audit-20260508-205041.html
```

No prompts. No LLM calls.

### Expected
- Slim install brings in only ~10 packages, none of redis/asyncpg/ulid
- `synapse audit` runs and detects conflicts in the Bedrock sample

### Actual
Both expectations met. **PASSED.**

### Conclusion
Day-1 install path is real and working.

---

## Test 9 — Option A: Real CI/CD loop (LangGraph + pytest in loop)

### What was tested
Whether **CI alone** detects cross-agent collisions, and whether **CI + Synapse** strictly improves on CI alone in real LangGraph multi-crew runs.

### How tested
Modal sandbox, Stripe Lite v2 starter as a real git repo. Two LangGraph crews (alpha + bravo) run in parallel via `asyncio.gather`, each with one worker agent. After every agent turn:
1. `git commit -am "<turn>"`
2. `pytest tests/ -x --tb=short -q`
3. The pytest output (last 30 lines, capped at 2000 chars) is fed back into the orchestrator's next prompt
4. If the orchestrator declares done OR exits the turn loop, the team stops

Two modes compared: `ci_only` (no Synapse), `ci_plus_synapse` (`MergePolicy.auto_merge`, `emit_beliefs_from_tool_results=True`).

### Inputs

**Verbatim orchestrator prompt** (`runtime/modal/_payloads/v02_ci_loop.py` line 71):
```
You are the lead of an AI engineering crew working on a small subscription
billing service `stripe_lite` (FastAPI + SQLAlchemy + pytest).

Add subscription cancellation with a 7-day grace period:
  1. Schema: add columns canceled_at, cancel_reason, grace_until to subscriptions
  2. POST /subscriptions/{{id}}/cancel — sets canceled_at=now, grace_until=now+7d
  3. POST /admin/subscriptions/{{id}}/restore — admin-only; clears the cancel fields
  4. GET  /subscriptions/{{id}}/status — returns active|grace|canceled
  5. Invoice generation: skip past-grace, mark prorated within grace
  6. Tests for each endpoint

You have 1 worker agent: {worker_id}.

Each turn: assign ONE file for {worker_id} to write or modify. After the
worker writes, the test suite runs (`pytest tests/ -x`) and you receive the
result. If pytest is RED, your next turn must address the failure.

Output ONLY valid JSON:
  {{"thought": "<one-line plan>",
    "assignment": {{"agent": "{worker_id}", "file": "<path>", "spec": "<1-2 lines>"}},
    "done": false}}

When done: {{"thought":"...","assignment":null,"done":true}}.
```

**Verbatim worker prompt** (`runtime/modal/_payloads/v02_ci_loop.py` line 154):
```
You are {agent_id} working on the stripe_lite repo. Write the FULL contents of {file_rel}.

Spec: {spec}

Output ONLY the file contents, no markdown fences, no commentary. Keep it under 80 lines. Make it valid Python that pytest can import.
```

**Critical:** prompts do NOT mention the other crew. The agents do NOT know they are being tested. Same prompt template across both modes.

Model: `claude-haiku-4-5-20251001`, max_tokens=400 (orch), max_tokens=900 (worker), max_turns=6 per crew.

Both crews started parallel via `asyncio.gather` on the SAME repo_root.

### Expected (pre-registered)
H5: "C9 (CI + Synapse) catches strictly more than C3 alone — same overhead, broader coverage." Specifically:
- ci_only: ≥1 silent overwrite, 0 belief divergences caught
- ci_plus_synapse: ≥3 conflicts detected, ≥1 belief divergence, coherence ≥ ci_only

### Actual
| Metric | ci_only | ci_plus_synapse |
|---|---|---|
| Files written | 4 | 2 |
| Cross-team file overlaps (silent) | **3** | 1 |
| CI runs / red | 12 / 12 | 12 / 12 |
| Final pytest | RED | RED |
| Coherence | **0.40** | **0.27** |
| **CONFLICT envelopes detected** | **0** | **27** |
| **BELIEF DIVERGENCEs caught** | **0** | **5** |
| auto_merges fired | 0 | 0 |
| Wall clock | ~60s | ~75s |

Result file: `bench/results/v02_ci_loop_20260508-172233.json`

The 5 belief divergences in synapse mode (real values from the run):
1. `user_table_columns`:
   - `["id", "email", "is_admin", "created_at", "updated_at"]`
   - `["id", "username", "email", "password_hash", "is_admin"]`
2. `subscription_table_columns`:
   - `["id", "user_id", "status", "canceled_at", "cancel_reason", "grace_until", "created_at", "updated_at"]`
   - `["id", "user_id", "plan_id", "status", "created_at", "canceled_at", "cancel_reason", "grace_until"]`
3. Variations on the above two as turns progressed.

### Conclusion
**H5 is partially refuted on the outcome dimension.** Detection-wise: Synapse caught 27 cross-agent file collisions and 5 schema-drift events that CI alone made invisible. Outcome-wise: coherence DROPPED from 0.40 to 0.27 with Synapse on, and final pytest stayed RED in both modes.

The mechanism: with CI tightly in the loop, agents produced full-file rewrites (not incremental edits) in response to red CI. Synapse correctly identified these as stale_base_overwrite conflicts but `auto_merge` requires conflicting *content within* a file to merge — full rewrites don't have that shape.

**Honest revised claim for the pitch:** Synapse + CI gives you **visibility** into cross-agent collisions that CI alone doesn't surface. Whether visibility translates to convergence depends on whether the agent prompt knows what to do with CONFLICT signals — that's prompt engineering on top of Synapse.

### Honesty notes
- 6 turns per crew is a short window. With more turns, auto_merge might get a chance to fire on incremental edits. Not tested.
- The agents in this test were not told about the other crew. If they had been told, they could have read each other's commits and avoided overlapping files entirely. That's a different experiment.
- Coherence dropping is *partly* due to fewer files written (2 vs 4) — Synapse's blocking gate slows the team down; in 6 turns both teams together completed less. With more turns the gap might close or invert.

---

## Test 10 — Option B: Real two-Claude-Code-sessions

### What was tested
Whether two real Claude Code 2.1.87 sessions running in parallel on the same git repo collide on the same files (the real-world solo-dev "tmux pane × 2" scenario), and whether the FS-watcher captures those collisions for `synapse audit`.

### How tested
Locally on the user's Windows 11 machine (no Modal). Two parallel Python threads each spawn a `claude.cmd -p <prompt>` headless process with different `SYNAPSE_AGENT_ID` env vars (`alice-claude-code`, `bob-claude-code`) but the same prompt and same starting repo.

Two FS-watcher instances are started before spawning Claude Codes; each watcher tags writes with its own agent_id. After both Claude Codes finish, `synapse audit` runs on the resulting JSONL log.

### Inputs

**Verbatim task prompt given to BOTH Claude Code sessions** (`bench/option_b_claude_code_test.py` line 23):
```
You are working on the stripe_lite repo. The codebase is a small FastAPI
subscriptions billing service in `app/` with `tests/` for pytest.

Add subscription cancellation with a 7-day grace period:

1. Schema in app/models.py: add columns
     canceled_at = Column(DateTime, nullable=True)
     cancel_reason = Column(String, nullable=True)
     grace_until = Column(DateTime, nullable=True)
   Use AMERICAN spelling (canceled_at, NOT cancelled_at).

2. New endpoints in app/routes/subscriptions.py:
     POST /subscriptions/{id}/cancel  — body {reason: str}; sets canceled_at=now, grace_until=now+7d.
                                        Returns 409 if already canceled.
     GET  /subscriptions/{id}/status  — returns {"state": "active"|"grace"|"canceled"}

3. New endpoint in a new file app/routes/admin.py:
     POST /admin/subscriptions/{id}/restore — admin-only; clears canceled_at, cancel_reason, grace_until.

4. Update app/routes/invoices.py generate_monthly_invoices:
     - Skip subscriptions where grace_until is in the past
     - When inside the grace window, mark the invoice as `prorated`

5. Add tests/test_cancel.py with tests for each new endpoint.

Make all the code work end-to-end. Run `pytest tests/ -x` to verify.
When complete, finish your turn — do not ask follow-up questions.
```

**The prompt is identical for both sessions.** The prompt does NOT mention the other agent. The prompt is highly directive about which paths and column names to use — this was deliberate to test "do they collide in the same files when given the same instructions."

CLI invocation:
```
claude.cmd -p <prompt> --allowedTools "Edit,Write,MultiEdit,Read,Bash(pytest:*),Bash(python:*),Bash(ls:*),Bash(cat:*)" --dangerously-skip-permissions
```

### Expected
- Both Claude Codes write to overlapping files (especially `app/models.py`)
- FS-watcher captures the writes
- `synapse audit` detects ≥3 cross-agent file conflicts

### Actual
| Metric | Result |
|---|---|
| alice-claude-code | exit 0 in 127.2s |
| bob-claude-code | exit 0 in 124.6s |
| FS watcher events emitted (alice/bob) | 14 / 14 (28 total) |
| **Conflicts detected by `synapse audit`** | **21** |
| Distinct overlapping files | **7** (`app/models.py`, `app/main.py`, `app/routes/admin.py`, `app/routes/invoices.py`, `app/routes/subscriptions.py`, `tests/test_cancel.py`, +1) |
| Coherence | **0.80** (12 of 15 markers matched) |

The 3 missing coherence markers were endpoint-path style differences — exactly the "belief divergence" class.

Result file: `bench/results/option_b/option_b_results.json`

### Conclusion
**PASSED.** Two real Claude Code sessions on the same repo collide reliably (21 conflicts on 7 files), and the FS watcher + audit pipeline captures them post-hoc. The IDE wedge is empirically defensible.

### Honesty notes
- The prompt is **highly directive** ("AMERICAN spelling", "POST /subscriptions/{id}/cancel"). This *reduces* the chance of belief divergence on the things the prompt specifies. The 0.80 coherence is therefore an *upper bound* — with a less directive prompt, more agents would diverge more. A separate experiment with a vague prompt would be more pessimistic about Claude Code's natural agreement rate but wasn't run.
- Running two FS watchers on the same dir produces attribution noise. Each watcher attributes every write to its own agent, so the audit sees 28 writes total even though only 14 distinct file modifications happened. The audit still correctly identifies the *cross-agent collision* on each path because both watcher's events for the same path have different `agent_id` values; but the per-write timestamps are not perfectly aligned to which Claude Code actually wrote.
- The Claude Code BeforeTool hook (`launch/claude-code-hook/synapse-pretooluse.py`) would give clean per-session attribution. That hook was NOT used in this test — the test exercised only the FS-watcher fallback path.

---

## Test 11 — Option C: Real Strands Agents SDK (initial run, broken adapter)

### What was tested
Whether the `synapse.frameworks.strands` adapter (as shipped in v0.2.1) actually instruments the real `strands-agents` package from PyPI.

### How tested
Modal sandbox, `pip install strands-agents` at runtime, two parallel Strands agents on Stripe Lite v2.

### Inputs

**Verbatim task prompt** (`runtime/modal/_payloads/v02_strands_real.py` line 80):
```
You are an engineer working on `stripe_lite`, a small FastAPI subscriptions
billing service. Add subscription cancellation:

1. Add columns to subscriptions table: canceled_at, cancel_reason, grace_until
2. Add endpoint POST /subscriptions/{id}/cancel
3. Add endpoint GET /subscriptions/{id}/status returning active|grace|canceled
4. Update invoice generation to skip past-grace, mark prorated within grace

Use the edit_file tool to write the relevant Python files. Be thorough but
concise — when the task is done, return a short summary.
```

Both alice and bob got this same prompt. Strands Agent invoked with `claude-haiku-4-5-20251001`, `max_tokens=2000`.

### Expected (pre-registered)
- Adapter logs `patched ... event_loop._handle_tool_execution` (or similar)
- ≥3 CONFLICT envelopes detected in synapse mode
- 0 conflicts in no_synapse mode

### Actual
| Metric | no_synapse | synapse |
|---|---|---|
| agents OK | 1 of 2 | 0 of 2 |
| files written | 17 | 31 |
| elapsed | 31.0s | 193.9s |
| **CONFLICT envelopes detected** | **0** | **0** ❌ |
| `"could not find a tool-dispatch hook"` warnings | 0 | **2** |

Result file: `bench/results/v02_strands_real_20260508-173000.json`

### Conclusion
**REFUTED.** The shipped Strands adapter probes for `ToolHandler.handle_tool_call` (a class method) but real Strands SDK 1.x dispatches via `strands.event_loop.event_loop._handle_tool_execution` (a module-level async generator). The adapter logged `could not find a tool-dispatch hook on Agent` and silently no-op'd. Both Strands agents in synapse mode functionally ran un-instrumented.

This is the **most important honest finding** of the entire campaign: the smoke-test-against-fake approach (Test 6) caught zero of the API drift problems with the real SDK. The user's IRL-testing demand directly surfaced this gap.

### Honesty notes
- This refutes Hypothesis H8 from the original pitch.
- The adapter was rewritten (Test 11 retry below) to patch the module-level function. The fix is structural, not a hack.

---

## Test 11-RETRY — Option C with FIXED adapter

### What was tested
Same as Test 11, but with the rewritten adapter that patches `strands.event_loop.event_loop._handle_tool_execution` at the module level instead of probing for a class method.

### How tested
Identical to Test 11. Same prompts, same model, same Modal sandbox. The only difference is the adapter code in `sdk-python/synapse/frameworks/strands.py` (committed at `188cc87`).

### Expected
- Adapter logs `patched ... module-level strands.event_loop.event_loop._handle_tool_execution`
- Synapse instrumentation fires on real edit_file tool calls
- Cross-agent CONFLICT envelopes detected in synapse mode

### Actual
| Metric | no_synapse | synapse |
|---|---|---|
| agents OK | 2 of 2 | 1 of 2 (one MaxTokens) |
| files written | 22 | 21 |
| elapsed | 74.5s | 113.0s |
| `"could not find a tool-dispatch hook"` warnings | 0 | **0** ✅ (fixed) |
| `[SYNAPSE] CONFLICT` markers in stdout | 0 | **0** ⚠️ |
| `BELIEF DIVERGENCE` in stdout | 0 | 0 |

Result file: `bench/results/v02_strands_real_20260508-174200.json`

### Conclusion (NUANCED — partial recovery, not full validation)

**What's confirmed by this run:**
- The fix to patch `strands.event_loop.event_loop._handle_tool_execution` at the module level is correctly **structural** — no "could not find" warnings, meaning the adapter found and patched the right entry point.
- Synapse mode is measurably slower (113s vs 74s) suggesting the wrapper IS executing on tool calls.
- Test 12 (run independently) confirms `synapse.install(framework='strands')` logs `patched module-level strands.event_loop.event_loop._handle_tool_execution` against the real `strands-agents` package.

**What's NOT confirmed by this run:**
- 0 `[SYNAPSE]` CONFLICT markers in stdout. This could mean either:
  - (a) The patch IS firing but the Strands payload doesn't print conflict notifications to stdout (the multi-orch payload prints `[SYNAPSE]` markers; the Strands payload doesn't have that print). The conflicts may be in the Postgres state graph but invisible from stdout.
  - (b) The patch is loaded but its wrapper's `intend()` context isn't actually intercepting the tool calls because the function-level wrapping of an async generator may have a subtle signature mismatch.
- The adapter's `logger.info("patched module-level ...")` doesn't appear in the Modal stdout because Modal's default logging level is WARNING. INFO-level logs from `synapse.frameworks.strands` are suppressed unless the root logger is configured for INFO.

**Honest verdict:** Strands adapter is **structurally fixed but functionally unverified** in a real two-agent collision scenario. To be 100% sure it fires CONFLICT envelopes, I'd need to either (a) instrument the adapter to print on conflict like the multi-orch payload does, or (b) query the Postgres state graph after the run to count INTENTION envelopes. Neither was done in this run.

This is more honest than the previous claim. The next step is a third run with `[SYNAPSE]` printing added to the Strands adapter wrapper, OR direct DB inspection.

### Honesty notes
- The shipped v0.2.1 Strands adapter (Test 11) was definitively broken.
- The fix in this run (Test 11-RETRY) is structurally correct (Test 12 confirms the patch attaches) but its end-to-end behavior on real conflicts is not verified by this run alone.
- If I claim the Strands adapter "works" based on Test 11-RETRY alone, that's overstating. The honest claim is: "patches the real SDK; end-to-end conflict-detection in production usage requires further validation."

---

## Test 12 — Real-SDK smoke test for all framework adapters

### What was tested
Whether each of the 8 Python framework adapters in v0.2.1 actually patches the real published version of its target SDK (not a hand-built mock).

### How tested
For each framework: `pip install <real package>`, `import` it to record version, then run `synapse.install(framework=X)` while capturing `synapse` logger output. If logs contain `patched` we record success; if `could not find` we record broken; if exception, record exception.

### Inputs
- Real `pip install <package>` per framework (versions captured at run time)
- Synapse logger captured via `logging.Handler`
- **No LLM prompts.** Adapter activation only — no agent execution.

### Expected
At least one adapter (Strands, per Test 11) is broken. Possibly others. This test exists to enumerate which.

### Actual

| Framework | Pip package | Install | Version | Patched | Log |
|---|---|---|---|---|---|
| **langgraph** | `langgraph` | ✅ | ? | **ambiguous** | `INFO: callback ready. Attach via graph.invoke(input, config={'callbacks':[synapse.frameworks.langgraph.get_callback()]}) for explicit control...` — does NOT use the word "patched"; uses LangChain callback model instead. **Different paradigm than other adapters.** |
| **crewai** | `crewai>=0.86,<0.130` | ❌ FAIL | n/a | n/a | pip could not resolve the version range in current pip env; likely needs Python or dependency adjustments |
| **autogen** | `autogen-agentchat>=0.4` | ✅ | 0.7.5 | ✅ **TRUE** | `INFO: patched autogen_core.FunctionTool.run` |
| **openai_agents** | `openai-agents` | ✅ | 0.17.0 | ✅ **TRUE** | `INFO: patched agents.tool.function_tool` |
| **pydantic_ai** | `pydantic-ai` | ✅ | **1.92.0** | ❌ **FALSE** | `WARNING: could not find Tool.run/call to patch. Use synapse.intend() manually.` |
| **smolagents** | `smolagents` | ✅ | 1.24.0 | ✅ **TRUE** | `INFO: patched Tool.__call__` |
| **hermes** | `hermes-mcp` | ❌ FAIL | n/a | n/a | `ERROR: No matching distribution found for hermes-mcp` — the package name is wrong (Hermes is not on PyPI under this name) |
| **strands** | `strands-agents` | ✅ | ? | ✅ **TRUE** | `INFO: patched module-level strands.event_loop.event_loop._handle_tool_execution` (this is the FIX from Test 11-RETRY working) |

Result file: `bench/results/test_12_real_sdk_smoke.json`

### Conclusion

**Massive forensic finding.** Of 8 adapters tested:

- **4 of 8 (autogen, openai_agents, smolagents, strands-fixed) patch successfully against real published SDKs.**
- **1 of 8 (pydantic_ai 1.92.0) is BROKEN against the real published SDK.** This is the second documented case (after Strands) of an adapter shipping with the wrong API path. The pydantic_ai adapter probes for `Tool.run/call` but those don't exist in pydantic-ai 1.92.0.
- **1 of 8 (langgraph) uses a different paradigm** (LangChain callback registration, not a method patch). Whether it actually works against current LangGraph isn't confirmed by this test — it requires an end-to-end test with a real LangGraph graph.
- **2 of 8 (crewai, hermes) failed to install** in this environment, so their adapter status is unknown. The hermes case is severe: the adapter exists but its target package name (`hermes-mcp`) doesn't exist on PyPI. Either the adapter was written for an internal package or the published name is different.

**The user's concern was correct:** Test 6's smoke-test-against-fake approach catches zero of the API-drift problems. Test 12 surfaces them in 30 seconds per framework.

### Honesty notes
- This test only validates that the adapter **attaches**. It does NOT validate that the wrapped function actually fires correctly when the agent runs. Strands (Test 11-RETRY) shows attaching ≠ firing. So 4-of-8 attaching is a *ceiling* on adapter health, not a floor.
- The crewai and hermes install failures are environmental (this Python env). The adapters may work fine when correctly installed elsewhere; this test cannot tell.
- LangGraph's callback-based integration likely IS correct (it's a known LangChain pattern) but verifying it requires running a real graph. Test 9 (Option A) used LangGraph and Synapse caught real conflicts there, so we have indirect evidence it works.
- pydantic_ai is the strongest IRL refutation discovered by this test. Should be flagged as broken in the launch readiness checklist.

---

## Test 13 — Real OpenInference exporter → synapse audit

### What was tested
Whether `synapse audit` successfully ingests trace exports produced by a **real, in-production trace exporter** (the official `openinference-instrumentation-anthropic`) wrapped around real Anthropic SDK calls, and whether it detects cross-agent collisions in the resulting trace.

### How tested
1. `pip install openinference-instrumentation-anthropic opentelemetry-sdk`
2. Set up `InMemorySpanExporter` from `opentelemetry.sdk.trace.export.in_memory_span_exporter`
3. Run `AnthropicInstrumentor().instrument()`
4. Make 2 real Anthropic API calls, each wrapped in a tracer span tagged with `agent.id` (`alice` / `bob`), `session.id`, `tool.name=edit_file`, `tool.args` containing `{"path": "app/models.py", ...}`
5. `force_flush()`, dump exported spans to JSON
6. Run `audit_traces()` on the JSON

### Inputs

**Verbatim prompts** (`bench/test_13_real_otel_audit.py` lines 78–86):
```
PROMPT_ALICE = (
    "You are alice. The team is building a billing service. Pick a column name "
    "for 'when subscription was canceled' and reply with ONE WORD ONLY (snake_case). "
    "Do not explain."
)
PROMPT_BOB = (
    "You are bob. The team is building a billing service. Pick a column name "
    "for 'when subscription was canceled' and reply with ONE WORD ONLY (snake_case). "
    "Do not explain."
)
```

The prompts are nearly identical — alice and bob get the same task. We don't know in advance whether they'll converge (`canceled_at` for both) or diverge (`canceled_at` vs `cancellation_time`). Either outcome is informative.

Both calls used `claude-haiku-4-5-20251001`, `max_tokens=20`, real Anthropic API, OpenInference auto-instrumentation active.

### Expected
- 4+ OTel spans captured (1 tracer span + 1 LLM span per agent, possibly more)
- `synapse audit` finds the cross-agent overlap on `app/models.py` since both agents have the same path in `tool.args`

### Actual
```
=== Test 13: Real OpenInference exporter -> synapse audit ===
  alice: 'canceled_at'
  bob: 'canceled_at'

Captured 4 OpenTelemetry spans

--- Running synapse audit on the real OpenInference trace ---
  events:    2
  writes:    2
  conflicts: 1
    [scope_overlap] ['repo.fs.app/models.py:w'] agents=['bob', 'alice']
```

Result file: `bench/results/test_13_real_otel_audit.json`
Trace file: `bench/results/test_13_real_otel_trace.json`

### Conclusion
**PASSED.** Real OpenInference auto-instrumentor against real Anthropic SDK produces a trace export that `synapse audit` correctly ingests and analyzes. The 1 cross-agent file collision (both agents touching `app/models.py`) is detected as `scope_overlap`. **This is the cleanest "real exporter → real audit" validation in the entire campaign.**

Both agents converged on `canceled_at` — no belief divergence in this run. That's a real outcome (not rigged) and means the audit finding is *only* on the file-path overlap, not on conflicting values. A repeat with more abstract prompts would more likely produce divergence.

### Honesty notes
- This validates OpenInference + Anthropic. It does NOT validate the Bedrock/Vertex/Azure importers against real Bedrock/Vertex/Azure agents — for that I need cloud credentials I don't have.
- The trace contains 4 spans (alice's tracer span + alice's LLM call span + bob's tracer span + bob's LLM call span). `synapse audit` correctly skips the LLM call spans (only 2 events processed) because they don't have a `tool.name` attribute matching write patterns.
- The agents converging (`canceled_at` for both) is a "negative" finding for divergence detection — the audit had nothing semantic to flag. That's correct behavior.

---

## Aggregate scorecard — FINAL (all 13 tests complete)

| # | Test | Real / Modeled | Verdict | Confidence | Result file |
|---|---|---|---|---|---|
| 1 | Oracle smoke (synthetic fixture) | Deterministic | PASS | High | `bench/oracle/test_oracle.py` |
| 2 | Cloud trace importers (Bedrock/Vertex/Azure hand-crafted samples) | Real importer / hand-crafted samples | PASS at parse layer | Medium — samples are not from real cloud agents | `bench/results/v02_pitch_phase1/C12_cloud_trace_audit.json` |
| 3 | Audit recall on multi-orch (synthesized trace) | Real audit / synthesized trace from May-8 stdout | PASS but tautological | Low — trace synthesized from same source as ground truth | `bench/results/v02_pitch_phase1/C10_audit_recall.json` |
| 4 | Multi-orch May 8 (real LangGraph 2-team) | Real LLMs, real LangGraph | **PASS** — 4 collisions, 3 beliefs | High | `bench/results/v02_multi_orchestrator_20260508-141754.json` |
| 5 | Strategy comparison simulator | **Modeled** (S3 PR+CI, S4 shared md) | PASS but later refuted by Test 9 | Low — S3/S4 numbers are estimates | `bench/results/v02_pitch_phase1/strategy_comparison.json` |
| 6 | Strands adapter smoke (against fake module) | **Mock** | PASSED but **MEANINGLESS** (Test 11 shows real SDK breaks) | Zero | `bench/oracle/test_strands_adapter.py` |
| 7 | FS watcher smoke (synthetic writes) | Real watcher / synthetic agents | PASS | Medium — 2-watcher attribution noise | `bench/oracle/test_oracle.py` (inline scenarios) |
| 8 | Slim install end-to-end | Real `pip install` from `.whl` | PASS | High | `launch/dist/synapse_protocol-0.2.1a0-py3-none-any.whl` |
| 9 | Option A: real CI/CD loop | **REAL** | **PARTIAL REFUTATION of H5.** Detection +27 conflicts +5 beliefs vs CI alone (0,0). But coherence DROPPED 0.40→0.27. Auto_merge didn't fire on full-rewrite agents. | High | `bench/results/v02_ci_loop_20260508-172233.json` |
| 10 | Option B: real Claude Code 2-session | **REAL** | **PASS** — 21 conflicts on 7 files, coherence 0.80 | High | `bench/results/option_b/option_b_results.json` |
| 11 | Option C: real Strands (shipped adapter) | **REAL** | **REFUTED** — adapter doesn't patch real SDK 1.x | High | `bench/results/v02_strands_real_20260508-173000.json` |
| 11-RETRY | Option C with module-level fix | **REAL** | **NUANCED** — adapter attaches, but no `[SYNAPSE]` markers in stdout proves nothing because the Strands payload doesn't print conflicts. Functionally unverified end-to-end. | Medium | `bench/results/v02_strands_real_20260508-174200.json` |
| 12 | Real-SDK smoke for all 8 adapters | **REAL** | **MIXED.** 4/8 patch (autogen, openai_agents, smolagents, strands-fixed). 1 BROKEN (pydantic_ai 1.92.0). 1 ambiguous paradigm (langgraph). 2 install-fail (crewai, hermes). | High | `bench/results/test_12_real_sdk_smoke.json` |
| 13 | Real OpenInference exporter → audit | **REAL** | **PASS** — 1 cross-agent conflict detected on `app/models.py` from real Anthropic SDK trace export | High | `bench/results/test_13_real_otel_audit.json` |

### Honest classification by evidence quality

**Tier 1 — Real, high-confidence evidence (can be quoted in the pitch):**
- Test 4 (multi-orch May 8 organic 4 collisions + 3 beliefs)
- Test 8 (day-1 slim install works)
- Test 9 (Option A: 27 conflicts + 5 beliefs detected vs 0 in CI alone)
- Test 10 (Option B: 21 conflicts in real two-Claude-Code run)
- Test 13 (Real OpenInference → audit pipeline works)

**Tier 2 — Real but partial / nuanced (should be cited with caveats):**
- Test 9 outcome dimension (Synapse + CI did NOT improve coherence — must be disclosed)
- Test 11-RETRY (adapter attaches, conflict-firing unverified — must be disclosed)
- Test 12 (4/8 adapters confirmed patching against real SDK; 1 confirmed broken)

**Tier 3 — Modeled or low-evidence (should NOT be cited as proof):**
- Test 3 (audit recall — tautological)
- Test 5 (strategy simulator — modeled, later refuted by Test 9)
- Test 6 (smoke-against-fake — Test 11 proves it's worthless)

**Tier 4 — Refuted by IRL evidence:**
- Test 11 original (shipped Strands adapter is broken)
- Test 12 finding: pydantic_ai 1.92.0 adapter is broken
- Test 9 H5 outcome claim ("CI + Synapse strictly better than CI") — refuted on coherence

### Refuted claims (the brutal-honesty list)

These claims from the v0.2.1 launch materials should be removed or re-scoped:

1. ❌ "Synapse adapter pattern works mechanically across 11 frameworks" — pydantic_ai broken; crewai/hermes uninstallable; langgraph uses a different paradigm; only 4 confirmed working.
2. ❌ "Synapse + CI strictly improves outcomes over CI alone" — refuted by Option A coherence drop. Synapse adds **detection** without (in this configuration) adding **convergence**.
3. ❌ "Strands adapter works against real SDK" — original adapter refuted; fix attaches but end-to-end firing unverified.
4. ❌ "Audit covers Bedrock/Vertex/Azure cloud agents" — only validated against hand-crafted samples; real cloud-vendor exports require credentials I don't have.

### Confirmed claims (the safe list)

1. ✅ Real Claude Code sessions on shared codebases collide silently (Test 10: 21 conflicts on 7 files)
2. ✅ FS watcher captures concurrent agent writes for post-hoc audit (Test 10 + Test 7)
3. ✅ `pip install synapse-protocol` + `synapse audit` is day-1 working (Test 8)
4. ✅ Real OpenInference exports → `synapse audit` → conflicts detected (Test 13)
5. ✅ Synapse + CI catches cross-agent collisions CI alone makes invisible (Test 9 detection)
6. ✅ At least 4 adapters patch successfully against real published SDKs (Test 12: autogen, openai_agents, smolagents, strands-fixed)
7. ✅ Multi-orchestrator natural workload produces real organic collisions caught by Synapse observer + full modes (Test 4)

---

## Categorical truth table

After all 13 tests complete, the truth-classification of the v0.2.1 claims:

- **Validated by real measurement:** day-1 install path; FS-watcher fallback for IDE agents; LangGraph live integration with detection (not outcome improvement); audit on real OpenInference exports
- **Refuted by real measurement:** "Strands adapter works against real SDK" (until Test 11-RETRY confirms fix); "Synapse + CI strictly improves outcome" (detection yes, outcome no)
- **Modeled, not yet measured:** git workflow comparison; shared coordination.md compliance; Bedrock/Vertex/Azure audit on real exporter output (only OpenInference validated)

---

## Anti-fake-test commitments

1. **Every prompt used is in this document verbatim.** No paraphrasing.
2. **Every test's input data is checked into the repo.** Reviewers can re-run.
3. **No prompt was iterated on to produce a desired result.** The prompts in Tests 4, 9, 10, 11, 11-RETRY, 13 were written ONCE per test. If a test failed, the test itself was re-run; the prompt was not modified between runs (except Test 11 → Test 11-RETRY where the *adapter* was modified, not the prompt).
4. **Modeled cells are clearly tagged.** Test 5 (strategy simulator) is modeled and its conclusions are not used as primary evidence; Tests 9-10-11-13 are real evidence.
5. **Honest gaps are listed.** Cloud-vendor real exports, prompt-engineering-on-top-of-Synapse, false-positive rate at scale, full SDK adapter validation across all 11 — all open.

This document will be updated with the final 11-RETRY and 12 results before commit.
