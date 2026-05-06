"""Unit tests for spec/conflict-semantics.md.

Runs without infrastructure — pure functions only.
"""

from __future__ import annotations

import pytest

from synapse.state import (
    conflicts,
    find_overlapping_scopes,
    has_write,
    parse_scope,
    patterns_intersect,
)


class TestParseScope:
    def test_no_modifier_defaults_rw(self) -> None:
        base, mode = parse_scope("auth.middleware")
        assert base == "auth.middleware"
        assert mode == "rw"

    def test_explicit_modifiers(self) -> None:
        assert parse_scope("auth.middleware:r") == ("auth.middleware", "r")
        assert parse_scope("auth.middleware:w") == ("auth.middleware", "w")
        assert parse_scope("auth.middleware:rw") == ("auth.middleware", "rw")

    def test_modifier_only_at_end(self) -> None:
        # ":r" earlier in path should not be treated as modifier
        base, mode = parse_scope("a:r.b")
        assert base == "a:r.b"
        assert mode == "rw"


class TestHasWrite:
    def test_write_modes(self) -> None:
        assert has_write("w")
        assert has_write("rw")

    def test_read_only(self) -> None:
        assert not has_write("r")


class TestPatternIntersect:
    def test_exact_match(self) -> None:
        assert patterns_intersect("auth.middleware", "auth.middleware")
        assert not patterns_intersect("auth.middleware", "auth.session")

    def test_single_segment_wildcard(self) -> None:
        assert patterns_intersect("auth.*", "auth.middleware")
        assert patterns_intersect("auth.middleware", "auth.*")
        # * does NOT match multiple segments
        assert not patterns_intersect("auth.*", "auth.middleware.config")
        assert not patterns_intersect("auth.middleware.config", "auth.*")

    def test_multi_segment_wildcard(self) -> None:
        assert patterns_intersect("auth.**", "auth.middleware")
        assert patterns_intersect("auth.**", "auth.middleware.config")
        assert patterns_intersect("auth.middleware.config", "auth.**")

    def test_overlapping_multi_wildcards(self) -> None:
        assert patterns_intersect("db.**", "db.users.**")
        assert patterns_intersect("db.users.**", "db.**")

    def test_disjoint(self) -> None:
        assert not patterns_intersect("auth.middleware", "db.users")
        assert not patterns_intersect("auth.*", "db.*")


class TestConflicts:
    def test_concurrent_reads_no_conflict(self) -> None:
        assert not conflicts("db.users.schema:r", "db.users.schema:r")

    def test_read_vs_write_conflicts(self) -> None:
        assert conflicts("db.users.schema:r", "db.users.schema:w")
        assert conflicts("db.users.schema:w", "db.users.schema:r")

    def test_competing_writes_conflict(self) -> None:
        assert conflicts("db.users.schema:w", "db.users.schema:w")

    def test_default_rw_treated_as_write(self) -> None:
        assert conflicts("auth.middleware", "auth.middleware")

    def test_disjoint_scopes_dont_conflict(self) -> None:
        assert not conflicts("auth.middleware:w", "db.users:w")

    def test_wildcard_catches_narrow(self) -> None:
        assert conflicts("db.users.**:w", "db.users.email:w")

    def test_wildcard_reads_safe(self) -> None:
        assert not conflicts("db.users.**:r", "db.users.email:r")


class TestFindOverlappingScopes:
    def test_returns_overlapping_subset(self) -> None:
        new_scopes = ["auth.middleware:w", "db.users:r"]
        existing = ["auth.middleware:r"]
        result = find_overlapping_scopes(new_scopes, existing)
        # auth.middleware:w (write) vs auth.middleware:r (read) -> conflict
        # db.users:r vs auth.middleware:r -> no conflict
        assert result == ["auth.middleware:w"]

    def test_empty_when_no_conflicts(self) -> None:
        assert find_overlapping_scopes(["a.b:r"], ["a.b:r"]) == []

    def test_handles_wildcards(self) -> None:
        result = find_overlapping_scopes(
            ["db.users.email:w"],
            ["db.users.**:w"],
        )
        assert result == ["db.users.email:w"]


class TestSpecExamplesFromDoc:
    """Walk-through examples from spec/conflict-semantics.md verbatim."""

    def test_case_1_clean_parallel_work(self) -> None:
        # Agent A: auth.middleware:w | Agent B: auth.session:w  -> no conflict
        assert not conflicts("auth.middleware:w", "auth.session:w")

    def test_case_2_concurrent_reads(self) -> None:
        # Both read same scope -> no conflict
        assert not conflicts("db.users.schema:r", "db.users.schema:r")

    def test_case_3_read_vs_write(self) -> None:
        assert conflicts("db.users.schema:r", "db.users.schema:w")

    def test_case_4_wildcard_catches_narrow(self) -> None:
        assert conflicts("db.users.**:w", "db.users.email:w")
