"""Reference implementation — the diff each crew should produce on models.py.

Adds 3 nullable columns to Subscription, in this exact spelling:

    canceled_at = Column(DateTime, nullable=True)
    cancel_reason = Column(String, nullable=True)
    grace_until = Column(DateTime, nullable=True)

We use AMERICAN spelling (canceled_at, not cancelled_at). This is the
arbitrary choice the agents have to make in alignment.
"""
EXPECTED_COLUMNS = {
    "canceled_at": "DateTime",
    "cancel_reason": "String",
    "grace_until": "DateTime",
}
