"""Reference for the new routes the agents add.

These are the exact paths + HTTP methods + status semantics:

    POST /subscriptions/{id}/cancel     -> 200 with updated sub
    POST /admin/subscriptions/{id}/restore  -> 200 with restored sub
    GET  /subscriptions/{id}/status     -> 200 {"state": "active"|"grace"|"canceled"}

State machine (driven by grace_until):
    - canceled_at IS NULL                   -> "active"
    - canceled_at SET, grace_until > now    -> "grace"
    - canceled_at SET, grace_until <= now   -> "canceled"

Already-canceled error:
    - POST /cancel on already-canceled  -> 409 (not 400, not 422)
"""
EXPECTED_ROUTES = [
    ("POST", "/subscriptions/{id}/cancel"),
    ("POST", "/admin/subscriptions/{id}/restore"),
    ("GET", "/subscriptions/{id}/status"),
]

EXPECTED_STATE_VALUES = ["active", "grace", "canceled"]
ALREADY_CANCELED_STATUS = 409
