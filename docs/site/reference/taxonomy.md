# Conflict taxonomy

Synapse uses three conflict kinds, aligned with the SCF taxonomy ([Acharya 2026](../prior-art/scf.md)):

| Synapse kind | SCF type | Triggers when |
|---|---|---|
| `scope_overlap` | Type 2 (Resource Contention) | Two agents hold concurrent intentions on the same scope |
| `stale_base_overwrite` | Type 3 (Causal Violation, write-write) | Agent B writes to a scope A wrote recently — likely never saw A's change |
| BELIEF divergence | Type 1 (Contradictory Intent) | Two agents emit contradictory values for the same belief key (e.g. login_endpoint = `/api/login` vs `/auth/login`) |

Each conflict carries `resolution_tier_hint` ∈ `{policy, capability, temporal, escalation}` — which tier of the SCF cascade would resolve it in live mode.

The scope syntax: `<namespace>.<resource>:<action>`, e.g. `repo.fs.app/models.py:w`, `db.users:w`, `http.subscriptions/_id/cancel:w`.
