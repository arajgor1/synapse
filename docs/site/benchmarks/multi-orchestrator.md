# Multi-orchestrator benchmark

Two independent LangGraph crews on the same task with no coordinator. Real Anthropic Haiku 4.5, real Modal sandbox, May 2026.

| Strategy | Silent file loss | Loud conflicts | Belief divergences caught |
|---|---|---|---|
| No coordination | 4 of 8 | 0 | 0 of 3 |
| Git branches + naive merge | 0 | 4 (loud markers) | 0 of 3 |
| PR + CI w/ pytest in loop | 3 | 1 | 1 of 3 |
| Shared coordination.md | 2 | 0 | 0 of 3 |
| **Synapse `MergePolicy.auto_merge`** | **0** | **4 auto-merged** | **3 of 3** |

3 organic belief divergences caught:

- `login_api_endpoint`: `/api/login` vs `/auth/login`
- `subscriptions_table_columns`: `[plan, seat_count, ...]` vs `[plan_id, seats, status, ...]`
- `register_form_fields`: `[email, password, confirmPassword]` vs `[email, password]`

Source: `bench/results/v02_pitch_phase1/RESULTS_REAL.md`.
