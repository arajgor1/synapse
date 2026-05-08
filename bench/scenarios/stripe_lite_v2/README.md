# Stripe Lite v2 — Pitch Campaign Scenario

A focused, repeatable two-crew task used across all 12 cells of the
v0.2.1 pitch campaign. The same task definition + starter repo +
reference impl + oracle is used in every cell; only the strategy
plug-in changes.

## The task (handed verbatim to every crew in every cell)

```
You are working on `stripe_lite`, a small subscriptions billing
service built with FastAPI + SQLAlchemy. The current version supports
creating subscriptions and listing invoices.

Add subscription cancellation with a 7-day grace period:

1. Schema:
   - Add `subscriptions.canceled_at` (nullable timestamp)
   - Add `subscriptions.cancel_reason` (nullable text)
   - Add `subscriptions.grace_until` (nullable timestamp)

2. Endpoints (all require auth, return JSON):
   - POST /subscriptions/{id}/cancel
       body: {reason: string}
       sets canceled_at=now, grace_until=now+7d
       returns 200 with the updated subscription
   - POST /admin/subscriptions/{id}/restore
       admin-only; clears canceled_at, cancel_reason, grace_until
       returns 200 with the restored subscription
   - GET /subscriptions/{id}/status
       returns {state: "active"|"grace"|"canceled"} based on dates

3. Invoice generation logic:
   - When generating invoices, skip any subscription where
     grace_until is in the past.
   - When inside the grace window, still generate the invoice but
     mark it as `prorated` for the remaining grace days.

4. Tests:
   - Add tests for each endpoint and the grace logic.

Modify the existing files; do not start a new project. Stop when the
task is complete.
```

## Why this task

- **Shape:** schema change + endpoint pair + business logic + tests.
  Mirrors a real PR.
- **Collision pressure:** schema + auth + invoice files are the
  obvious targets, both crews will reach for them.
- **Belief divergence pressure:** "subscription state values"
  (active/grace/canceled vs active/cancelled/expired), endpoint
  paths (/cancel vs /subscriptions/cancel), column names
  (canceled_at vs cancelled_at, grace_until vs grace_period_end),
  status code on already-canceled (409 vs 400). All natural
  decisions a crew has to make without coordinating.
- **Same task as `v02_sdlc_billing`** in shape so we can reuse the
  coherence-marker scoring approach.

## Files in this directory

- `starter/` — the FastAPI repo each crew starts from (~400 LOC)
- `reference/` — hand-written correct implementation used for
  coherence scoring (~150 LOC of additions)
- `markers.json` — the list of (file, marker, expected_value) tuples
  the coherence scorer checks
