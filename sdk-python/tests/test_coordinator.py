"""Tests for the coordinator's belief-divergence detector.

Pure-function module, no I/O — fast unit tests.
"""

from __future__ import annotations

import sys
import os

# Allow importing runtime modules
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO_ROOT)

from runtime.coordinator.belief_divergence import (
    AgentBelief,
    BeliefDivergence,
    detect_divergences,
    beliefs_from_db_rows,
)


class TestEvidentialWeight:
    def test_observed_full_confidence(self) -> None:
        b = AgentBelief("a", "k", 1, 1.0, "observed")
        assert b.evidential_weight == 1.0

    def test_assumed_lower_weight(self) -> None:
        observed = AgentBelief("a", "k", 1, 1.0, "observed").evidential_weight
        assumed = AgentBelief("a", "k", 1, 1.0, "assumed").evidential_weight
        assert assumed < observed

    def test_low_confidence_clamps(self) -> None:
        b = AgentBelief("a", "k", 1, 0.0, "observed")
        assert b.evidential_weight == 0.0


class TestDetectDivergences:
    def test_same_value_no_divergence(self) -> None:
        beliefs = [
            AgentBelief("a", "db.type", "postgres", 0.9, "observed"),
            AgentBelief("b", "db.type", "postgres", 0.7, "inferred"),
        ]
        assert detect_divergences(beliefs) == []

    def test_distinct_values_flagged(self) -> None:
        beliefs = [
            AgentBelief("a", "db.type", "postgres", 0.95, "observed"),
            AgentBelief("b", "db.type", "mysql", 0.60, "assumed"),
        ]
        out = detect_divergences(beliefs)
        assert len(out) == 1
        d = out[0]
        assert d.key == "db.type"
        assert "postgres" in d.distinct_values
        assert "mysql" in d.distinct_values
        assert d.severity > 0

    def test_severity_higher_with_more_distinct(self) -> None:
        two_values = [
            AgentBelief("a", "k", 1, 1.0, "observed"),
            AgentBelief("b", "k", 2, 1.0, "observed"),
        ]
        three_values = [
            AgentBelief("a", "k", 1, 1.0, "observed"),
            AgentBelief("b", "k", 2, 1.0, "observed"),
            AgentBelief("c", "k", 3, 1.0, "observed"),
        ]
        s2 = detect_divergences(two_values)[0].severity
        s3 = detect_divergences(three_values)[0].severity
        assert s3 > s2

    def test_low_confidence_lowers_severity(self) -> None:
        confident = [
            AgentBelief("a", "k", 1, 1.0, "observed"),
            AgentBelief("b", "k", 2, 1.0, "observed"),
        ]
        uncertain = [
            AgentBelief("a", "k", 1, 0.3, "assumed"),
            AgentBelief("b", "k", 2, 0.3, "assumed"),
        ]
        s_conf = detect_divergences(confident)[0].severity
        s_unc = detect_divergences(uncertain)[0].severity
        assert s_unc < s_conf

    def test_multiple_keys_independent(self) -> None:
        beliefs = [
            AgentBelief("a", "db.type", "postgres", 0.9, "observed"),
            AgentBelief("b", "db.type", "mysql", 0.5, "assumed"),
            AgentBelief("a", "auth.method", "jwt", 0.9, "observed"),
            AgentBelief("b", "auth.method", "jwt", 0.7, "inferred"),
        ]
        out = detect_divergences(beliefs)
        keys = {d.key for d in out}
        assert keys == {"db.type"}  # auth.method matches; only db.type diverges

    def test_sorted_by_severity_desc(self) -> None:
        beliefs = [
            # Mild divergence (low confidence assumed)
            AgentBelief("a", "k1", 1, 0.3, "assumed"),
            AgentBelief("b", "k1", 2, 0.3, "assumed"),
            # Strong divergence (observed)
            AgentBelief("a", "k2", 1, 1.0, "observed"),
            AgentBelief("b", "k2", 2, 1.0, "observed"),
        ]
        out = detect_divergences(beliefs)
        # Strongest first
        assert out[0].key == "k2"
        assert out[1].key == "k1"

    def test_float_fuzz(self) -> None:
        beliefs = [
            AgentBelief("a", "rate", 0.05, 0.9, "observed"),
            AgentBelief("b", "rate", 0.05000000001, 0.9, "observed"),
        ]
        # Should not flag — values are equal within fuzz
        assert detect_divergences(beliefs) == []


class TestBeliefsFromDBRows:
    def test_typical_row_shape(self) -> None:
        rows = [
            {"agent_id": "a", "key": "db.type", "value": "postgres",
             "confidence": 0.9, "source": "observed"},
        ]
        out = beliefs_from_db_rows(rows)
        assert len(out) == 1
        assert out[0].agent_id == "a"
        assert out[0].value == "postgres"
