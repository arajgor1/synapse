"""Tests for v0.2.2 SCF-aligned features:
  - Resolution-tier hint (policy / capability / temporal)
  - SAS drift score per agent pair
  - DEFAULT_CRITICAL_SCOPE_PREFIXES routing
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from synapse.audit import (
    AuditEvent,
    audit_traces,
    compute_sas,
    detect_conflicts,
    DEFAULT_CRITICAL_SCOPE_PREFIXES,
)


def _ev(agent_id: str, scope: list[str], ts: int, session: str = "s") -> AuditEvent:
    e = AuditEvent(
        trace_id="t", span_id=f"sp{ts}", agent_id=agent_id, session_id=session,
        tool_name="edit_file", ts_start_ms=ts, ts_end_ms=ts + 100,
        tool_args={"path": scope[0].split(".")[1] if "." in scope[0] else "x"},
    )
    e.scope_inferred = scope
    return e


class TestResolutionTier:
    def test_billing_scope_is_policy_tier(self):
        events = [
            _ev("alice", ["billing.charge.user_42:w"], 1000),
            _ev("bob", ["billing.charge.user_42:w"], 1500),
        ]
        conflicts = detect_conflicts(events, write_only=False)
        assert len(conflicts) == 1
        assert conflicts[0].resolution_tier_hint == "policy"

    def test_admin_agent_is_capability_tier(self):
        events = [
            _ev("normal_user", ["repo.fs.foo.py:w"], 1000),
            _ev("alice_admin", ["repo.fs.foo.py:w"], 1500),
        ]
        conflicts = detect_conflicts(events, write_only=False)
        assert len(conflicts) == 1
        assert conflicts[0].resolution_tier_hint == "capability"

    def test_default_is_temporal(self):
        events = [
            _ev("alice", ["repo.fs.foo.py:w"], 1000),
            _ev("bob", ["repo.fs.foo.py:w"], 1500),
        ]
        conflicts = detect_conflicts(events, write_only=False)
        assert len(conflicts) == 1
        assert conflicts[0].resolution_tier_hint == "temporal"

    def test_critical_scope_prefixes_overridable(self):
        events = [
            _ev("alice", ["app.cancel.user_42:w"], 1000),
            _ev("bob", ["app.cancel.user_42:w"], 1500),
        ]
        # Default prefixes don't match
        c_default = detect_conflicts(events, write_only=False)
        assert c_default[0].resolution_tier_hint == "temporal"
        # Custom prefix bumps it to policy
        c_custom = detect_conflicts(
            events, write_only=False,
            critical_scope_prefixes=("app.cancel.",),
        )
        assert c_custom[0].resolution_tier_hint == "policy"


class TestSASDriftScore:
    def test_two_agents_same_scope_same_time_high_sas(self):
        # alice at [1000, 1100], bob at [1050, 1150] — overlap=50, union=150
        events = [
            _ev("alice", ["repo.fs.foo.py:w"], 1000),
            _ev("bob", ["repo.fs.foo.py:w"], 1050),
        ]
        sas = compute_sas(events)
        assert len(sas) == 1
        pair = sas[0]
        assert pair.entity_overlap == 1.0  # identical scope set
        assert pair.action_consistency == 1.0  # identical tool name
        assert pair.temporal_alignment > 0.3  # 50/150 = 0.33
        assert pair.sas > 0.85  # 0.5*1 + 0.3*1 + 0.2*0.33 = 0.866

    def test_disjoint_agents_zero_overlap(self):
        events = [
            _ev("alice", ["repo.fs.foo.py:w"], 1000),
            _ev("bob", ["repo.fs.bar.py:w"], 100_000),  # different scope, much later
        ]
        sas = compute_sas(events)
        assert len(sas) == 1
        pair = sas[0]
        assert pair.entity_overlap == 0.0
        # tool name still matches → action consistency high; but
        # composite SAS should still be lower than the identical case
        assert pair.sas < 0.7

    def test_no_pair_for_single_agent(self):
        events = [_ev("alice", ["x:w"], 1000), _ev("alice", ["y:w"], 2000)]
        assert compute_sas(events) == []

    def test_sas_per_session(self):
        events = [
            _ev("alice", ["x:w"], 1000, session="s1"),
            _ev("bob", ["x:w"], 1100, session="s1"),
            _ev("alice", ["y:w"], 2000, session="s2"),
            _ev("bob", ["y:w"], 2100, session="s2"),
        ]
        pairs = compute_sas(events)
        assert len(pairs) == 2
        assert {p.session_id for p in pairs} == {"s1", "s2"}


class TestCriticalScopePrefixes:
    def test_defaults_are_sensible(self):
        # Smoke: the defaults exist and cover obvious enterprise patterns
        prefixes = DEFAULT_CRITICAL_SCOPE_PREFIXES
        assert any(p.startswith("billing.") for p in prefixes)
        assert any(p.startswith("prod.") for p in prefixes)
        assert any(p.startswith("secrets.") for p in prefixes)
        assert any(p.startswith("iam.") for p in prefixes)


class TestPipelineWithSAS:
    def test_audit_traces_includes_sas_pairs(self):
        # Use the existing multi-orch synthesized trace
        trace_data = {
            "spans": [
                {
                    "name": "edit_file",
                    "spanId": "sp1",
                    "traceId": "tr1",
                    "startTime": "2026-05-09T12:00:00Z",
                    "endTime": "2026-05-09T12:00:01Z",
                    "attributes": {
                        "openinference.span.kind": "TOOL",
                        "tool.name": "edit_file",
                        "tool.args": '{"path": "models.py"}',
                        "agent.id": "alice",
                        "session.id": "s1",
                    },
                },
                {
                    "name": "edit_file",
                    "spanId": "sp2",
                    "traceId": "tr1",
                    "startTime": "2026-05-09T12:00:02Z",
                    "endTime": "2026-05-09T12:00:03Z",
                    "attributes": {
                        "openinference.span.kind": "TOOL",
                        "tool.name": "edit_file",
                        "tool.args": '{"path": "models.py"}',
                        "agent.id": "bob",
                        "session.id": "s1",
                    },
                },
            ]
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(trace_data, f)
            fpath = f.name
        try:
            report = audit_traces(fpath)
            assert len(report.sas_pairs) == 1
            assert report.sas_pairs[0].sas > 0.7
            assert report.conflict_tiers == {"temporal": 1}
            # JSON dict round-trip
            d = report.to_json_dict()
            assert "sas_pairs" in d
            assert "conflict_tiers" in d
            assert d["conflict_tiers"]["temporal"] == 1
        finally:
            Path(fpath).unlink()
