# Synapse v0.2 — Benchmark suite

This doc summarizes every live, real-LLM benchmark in the v0.2 release.
Each benchmark runs in a clean Modal sandbox (Debian + Python 3.11 + Node 20
+ Redis + Postgres) with a real Anthropic Haiku model behind every agent.

| # | Demo                                  | Headline question                                                                                             | Modes compared                                          | Cost  |
|---|---------------------------------------|---------------------------------------------------------------------------------------------------------------|---------------------------------------------------------|-------|
| 1 | `real_app_instagram`                  | Does scope-overlap detection catch silent file overwrites that fire-and-forget agents miss?                   | `no_synapse` vs `with_synapse`                          | ~$0.40 |
| 2 | `real_app_data_analysis`              | Do BELIEFs catch semantic conflicts when there's zero file overlap?                                            | `no_synapse` vs `with_synapse`                          | ~$0.30 |
| 3 | `v02_w4_auto_merge`                   | Does `MergePolicy.auto_merge` produce a final `models/user.py` containing all 3 engineers' fields?            | `no_synapse` vs `with_synapse_redirect` vs `with_synapse_automerge` | ~$0.50 |
| 4 | `v02_w5_belief_divergence`            | Does `emit_beliefs_from_tool_results=True` auto-detect 3 distinct revenue formulas across 3 disjoint files?   | `no_synapse` vs `with_synapse` vs `with_synapse_beliefs`| ~$0.20 |
| 5 | `v02_crewai_live` + `v02_langgraph_live` | Does `synapse.install(framework=...)` auto-instrument a real LangGraph / CrewAI workflow end-to-end?       | `with_synapse` only (instrumentation correctness)        | ~$0.30 |
| 6 | **`v02_sdlc_billing`** (this design) | On a realistic 6-agent SDLC workflow, does Synapse improve coherence on a multi-tenant SaaS billing platform? | `no_synapse` vs `with_synapse_redirect` vs `with_synapse_full` | ~$6.00 |

All results live in `bench/results/`. Re-run any of them with:

```bash
modal run runtime/modal/framework_sandbox.py::<entrypoint>
```

---

## 1 · `real_app_instagram` — scope-overlap detection on a 4-agent backend

**Workload.** Four engineers (`db`, `api`, `auth`, `feed`) each write 3
sequential files. `models/user.py` is touched by db + api + auth (3-way),
`api/posts.py` by api + feed (2-way).

**Modes**

- `no_synapse` — agents fire in parallel, last writer wins.
- `with_synapse` — every tool call wrapped via
  `wrap_tool_call_for_synapse`; CONFLICT envelopes routed to per-agent
  inboxes when scopes overlap.

**Metrics (placeholders — re-run separately)**

| Metric                              | `no_synapse` | `with_synapse` |
|-------------------------------------|--------------|----------------|
| Total file-write steps              | TBD          | TBD            |
| Unique files written                | TBD          | TBD            |
| Contended files (≥2 writers)        | TBD          | TBD            |
| INTENTION envelopes on stream       | 0            | TBD            |
| RESOLUTION envelopes on stream      | 0            | TBD            |
| CONFLICT envelopes routed to inbox  | 0            | TBD            |
| Tokens in / out                     | TBD          | TBD            |
| Wall-clock (s)                      | TBD          | TBD            |

**Expected pattern.** Both modes write the same files. Only `with_synapse`
emits CONFLICT envelopes for the contended ones — the no-Synapse run is
silent about the overwrites. This is the most basic form of the value
prop: "you can't fix what you can't see."

Entrypoint: `modal run runtime/modal/framework_sandbox.py::v02_instagram`
Payload: `runtime/modal/_payloads/real_app_instagram.py`

---

## 2 · `real_app_data_analysis` — BELIEFs on disjoint files

**Workload.** Three data-team agents (`cleaner`, `analyst`,
`finance_lead`) each write to a *different* file (zero scope overlap),
but each computes `revenue` differently:

- `cleaner`        — `revenue = qty * price`
- `analyst`        — `revenue = qty * price * (1 - discount)`
- `finance_lead`   — `revenue = qty * price - returns`

**Modes**

- `no_synapse` — beliefs not emitted, divergence not detected.
- `with_synapse` — manual `emit_belief` calls.

**Metrics (placeholders)**

| Metric                          | `no_synapse` | `with_synapse` |
|---------------------------------|--------------|----------------|
| BELIEFs persisted (PG)          | 0            | TBD (≥3)       |
| Live divergences detected       | 0            | TBD (≥1)       |
| Tokens in / out                 | TBD          | TBD            |

Entrypoint: `modal run runtime/modal/framework_sandbox.py::v02_data_analysis`
Payload: `runtime/modal/_payloads/real_app_data_analysis.py`

---

## 3 · `v02_w4_auto_merge` — MergePolicy.auto_merge on the User model

**Workload.** Three engineers all generate User-model code via real Haiku
and write to `models/user.py`. The `db_engineer` adds `created_at`, the
`api_engineer` adds `bio + avatar_url`, the `auth_engineer` adds
`password_hash + last_login`.

**Modes**

- `no_synapse` — last writer wins, only one engineer's fields survive.
- `with_synapse` (redirect) — CONFLICTs raised, file still overwritten.
- `with_synapse_automerge` — auto_merge runs through BYO-LLM; final file
  should contain fields from all 3 engineers.

**Metrics (placeholders)**

| Metric                            | `no_synapse` | `redirect` | `auto_merge` |
|-----------------------------------|--------------|------------|--------------|
| Auto-merges performed              | 0            | 0          | TBD (≥2)     |
| CONFLICT envelopes                 | 0            | TBD        | TBD          |
| Markers surviving (out of 3)       | 1            | 1          | 3            |
| Tokens in / out                    | TBD          | TBD        | TBD          |
| Elapsed (s)                        | TBD          | TBD        | TBD          |

**Expected pattern.** `markers_surviving` is the headline number — only
`auto_merge` should hit 3/3.

Entrypoint: `modal run runtime/modal/framework_sandbox.py::v02_w4`
Payload: `runtime/modal/_payloads/v02_w4_auto_merge.py`

---

## 4 · `v02_w5_belief_divergence` — auto-extract beliefs from tool results

**Workload.** Same data-team scenario as #2, but the agents do **not**
manually call `emit_belief`. Instead, `synapse.install(emit_beliefs_from_tool_results=True)` is set, and the BELIEF
extractor runs over each successful intend's `state_diff` via BYO-LLM.

**Modes**

- `no_synapse` — extractor inactive (no Synapse).
- `with_synapse` — installed but flag is off; extractor inactive.
- `with_synapse_beliefs` — flag on; extractor runs, divergence detected
  live as agents emit their inferred beliefs.

**Metrics (placeholders)**

| Metric                          | `no_synapse` | `with_synapse` | `with_synapse_beliefs` |
|---------------------------------|--------------|----------------|------------------------|
| BELIEFs in PG                   | 0            | 0              | TBD (≥3)               |
| Live divergences caught         | 0            | 0              | TBD (≥1)               |
| Final divergences               | 0            | 0              | TBD                    |
| Tokens in / out                 | TBD          | TBD            | TBD                    |

Entrypoint: `modal run runtime/modal/framework_sandbox.py::v02_w5`
Payload: `runtime/modal/_payloads/v02_w5_belief_divergence.py`

---

## 5 · Framework adapters — `crewai` + `langgraph` live

These two prove `synapse.install(framework=...)` auto-instruments real
agent frameworks. They're correctness checks, not comparative benchmarks
— there's no "no_synapse" mode here.

**Metrics (placeholders)**

| Metric                          | `crewai` | `langgraph` |
|---------------------------------|----------|-------------|
| INTENTIONs emitted              | TBD      | TBD         |
| RESOLUTIONs emitted             | TBD      | TBD         |
| Cost reports emitted            | TBD      | TBD         |
| Tokens in / out                 | TBD      | TBD         |

Entrypoints: `v02_crewai`, `v02_langgraph`
Payloads: `runtime/modal/_payloads/v02_crewai_live.py`,
`runtime/modal/_payloads/v02_langgraph_live.py`

---

## 6 · `v02_sdlc_billing` — full SDLC on a multi-tenant SaaS billing platform

The flagship v0.2 benchmark. A realistic 4-stage, 6-agent product-dev
workflow where every Synapse v0.2 mechanism is exercised under load:
scope-overlap CONFLICTs, `MergePolicy.auto_merge`, `critical_scopes`,
and `emit_beliefs_from_tool_results=True` divergence detection.

### Workload

| Stage | Agents (parallelism)                                                   | Files (per stage)                                                    |
|-------|------------------------------------------------------------------------|----------------------------------------------------------------------|
| 1. Requirements | `product_manager` (sequential)                              | `requirements.md`                                                    |
| 2. Architecture | `architect` (sequential, sees Stage 1)                       | `ARCHITECTURE.md` + 5 `models/*.js` skeletons                        |
| 3. Implementation | `backend_engineer`, `frontend_engineer`, `integrations_engineer` (parallel) | `routes/*.js`, `services/*.js`, `dashboard/*.tsx`, `webhooks/stripe.js`, plus rewrites of contended models, plus `.env.example` |
| 4. QA + DevOps  | `qa_engineer`, `devops_engineer` (parallel)                  | `tests/*.test.js`, `Dockerfile`, `.github/workflows/ci.yml`, plus rewrites of contended models, plus `.env.example` |

**~25-30 source files generated by real Haiku LLM calls, max 600 tokens
each.**

### Real conflicts planted

Multi-writer collisions (scope overlap):

| File                       | Writers                                                              | Stage |
|----------------------------|----------------------------------------------------------------------|-------|
| `models/User.js`           | `architect`, `backend_engineer`, `integrations_engineer`, `qa_engineer` | 2,3,4 |
| `models/Subscription.js`   | `architect`, `backend_engineer`, `integrations_engineer`, `qa_engineer` | 2,3,4 |
| `.env.example`             | `backend_engineer`, `frontend_engineer`, `integrations_engineer`, `devops_engineer` | 3,4 |

Naming-convention collision on `.env.example` (semantic, exposed via raw text):
`STRIPE_KEY` (backend) vs `VITE_STRIPE_API_KEY` (frontend) vs
`STRIPE_SECRET` (integrations) vs `STRIPE_API_KEY` (devops).

BELIEF divergences (no scope overlap, surfaced via `state_diff_extras`):

| Belief key            | Distinct values across agents                                                  |
|-----------------------|--------------------------------------------------------------------------------|
| `pricing_model`       | `per_seat` (PM) vs `usage_based` (architect) vs `hybrid` (backend_engineer)    |
| `tax_calculation`     | `included` (PM, frontend) vs `added_at_checkout` (backend) vs `stripe_tax_api` (architect, integrations) |
| `currency_handling`   | `USD_only` (PM) vs `multi_currency` (architect)                                 |

### Modes compared

| Mode                       | Synapse install args                                                                                   |
|----------------------------|--------------------------------------------------------------------------------------------------------|
| `no_synapse`               | (none — agents fire-and-forget)                                                                         |
| `with_synapse_redirect`    | `merge_policy=MergePolicy.redirect`                                                                     |
| `with_synapse_full`        | `merge_policy=MergePolicy.auto_merge`, `emit_beliefs_from_tool_results=True`, `critical_scopes=["repo.fs.routes.billing.*", "repo.fs.webhooks.stripe.*"]` |

### Metrics captured (per mode)

- Wall-clock elapsed (s)
- Total LLM tokens in / out (and dollar estimate)
- File-write steps run
- Unique files written
- Contended files (count + breakdown of writers per file)
- CONFLICTs total, split by `kind` (`scope_overlap` vs `stale_base_overwrite`)
- Auto-merges performed
- `critical_scope` aborts (mode 3 only)
- BELIEFs persisted in PG
- Live divergences during the run + final divergences after
- **Coherence score** = (markers surviving in final contended files) /
  (markers expected). The MARKERS table in the payload defines what each
  agent *should* have contributed; we regex-match against the final file.

### Expected metric ranges

> Estimates only — actual numbers will be filled in after the first
> Modal run. Use these as rough acceptance criteria.

| Metric                          | `no_synapse`   | `with_synapse_redirect` | `with_synapse_full`     |
|---------------------------------|----------------|-------------------------|-------------------------|
| Wall-clock (s)                  | 60-120         | 80-160                  | 120-240                 |
| Tokens out                      | 12k-18k        | 12k-18k                 | 18k-28k (auto_merge)    |
| Unique files written            | ~25            | ~25                     | ~25                     |
| Contended files                 | 3              | 3                       | 3                       |
| CONFLICTs total                 | 0              | 6-12                    | 6-12                    |
| `scope_overlap` CONFLICTs       | 0              | ≥6                      | ≥6                      |
| Auto-merges performed           | 0              | 0                       | ≥4                      |
| `critical_scope` aborts         | 0              | 0                       | 0-2                     |
| BELIEFs in PG                   | 0              | 0                       | ≥6                      |
| Final divergences               | 0              | 0                       | ≥2 (`pricing_model`, `tax_calculation`) |
| **Coherence score**             | **0.20-0.40**  | **0.20-0.40**           | **0.65-0.85**           |
| Estimated cost                  | ~$0.50         | ~$0.60                  | ~$0.90                  |

### Cost analysis

Haiku 4.5 pricing (rough): $1.00 / 1M in, $5.00 / 1M out.

Per mode, the agents do roughly:
- 25 LLM calls × ~600 tokens out × $5/M = **$0.075 output**
- 25 LLM calls × ~250 tokens in × $1/M = **$0.006 input**
- Per-agent file-gen subtotal: **~$0.08/mode**

Mode 3 (`with_synapse_full`) adds BYO-LLM auto-merges (~5 calls at
~1500 tokens out each) and the BELIEF extractor (~10 calls at ~400
tokens out each):
- Auto-merges: 5 × 1500 × $5/M = $0.038
- Extractor:  10 × 400 × $5/M = $0.020
- Subtotal added in mode 3: **~$0.06**

**Round-trip estimate per run: ~$0.30**, but assume Anthropic prompt
caching is cold and observability overhead doubles that — budget **$2.00
per run, $6.00 for all 3 modes**. Hard ceiling enforced by `max_tokens`
caps in the payload.

### Entrypoint

```bash
modal run runtime/modal/framework_sandbox.py::v02_sdlc
```

Payload: `runtime/modal/_payloads/v02_sdlc_billing.py`
Result file: `bench/results/v02_sdlc_billing_<timestamp>.json`

### What "winning" looks like

- `coherence_score` for `with_synapse_full` is **at least 2x higher**
  than `no_synapse` on the same workload. This is the headline number
  for the launch blog.
- ≥ 6 CONFLICT envelopes routed in synapse modes; 0 in `no_synapse`.
- ≥ 2 BELIEF divergences caught in `with_synapse_full`.
- All ≥ 4 auto-merges happen in `with_synapse_full`.
- `with_synapse_full` adds latency vs `no_synapse` (~2× wall-clock is
  acceptable; auto_merge does extra LLM work).

### What would falsify the demo

- `coherence_score` flat or *lower* in synapse modes → auto_merge is
  silently failing or the BYO-LLM is dropping fields.
- 0 CONFLICTs raised → the gate window is too short or scope grammar is
  wrong.
- Wall-clock for `with_synapse_full` >> 5× `no_synapse` → the policy
  invocations are sequential when they shouldn't be.
- 0 divergences → the `state_diff_extras` aren't getting picked up by
  the extractor (regression in the v0.2-w5 path).
