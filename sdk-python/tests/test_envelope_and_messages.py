"""Tests for Envelope construction and message round-tripping."""

from __future__ import annotations

import json

import pytest

from synapse.messages import (
    AgentRegistration,
    BackendCapabilities,
    Belief,
    Block,
    Conflict,
    ConflictingIntention,
    Envelope,
    Intention,
    MessageType,
    Pivot,
    Resolution,
    Thought,
    PAYLOAD_BY_TYPE,
)


def _new_intention() -> Intention:
    return Intention(
        action={"tool": "edit_file", "args": {"path": "auth/middleware.py"}},
        scope=["auth.middleware:w"],
        expected_outcome="Refactor middleware",
    )


class TestEnvelope:
    def test_make_creates_valid_ulid(self) -> None:
        env = Envelope.make(
            type=MessageType.INTENTION,
            agent_id="agent_a",
            session_id="sess_1",
            payload=_new_intention(),
        )
        assert len(env.msg_id) == 26
        assert env.timestamp_ms > 0

    def test_round_trip_json(self) -> None:
        env = Envelope.make(
            type=MessageType.INTENTION,
            agent_id="agent_a",
            session_id="sess_1",
            payload=_new_intention(),
        )
        as_json = env.model_dump_json()
        decoded = Envelope.model_validate_json(as_json)
        assert decoded.msg_id == env.msg_id
        assert decoded.type == MessageType.INTENTION
        assert decoded.payload["scope"] == ["auth.middleware:w"]

    def test_payload_can_be_dict(self) -> None:
        env = Envelope.make(
            type=MessageType.BELIEF,
            agent_id="agent_a",
            session_id="sess_1",
            payload={
                "key": "db.type",
                "value": "postgres",
                "confidence": 1.0,
                "source": "observed",
            },
        )
        assert env.payload["key"] == "db.type"

    def test_invalid_ulid_rejected(self) -> None:
        with pytest.raises(Exception):
            Envelope(
                msg_id="not-a-ulid",
                type=MessageType.INTENTION,
                agent_id="a",
                session_id="s",
                timestamp_ms=0,
                payload={},
            )


class TestPayloadModels:
    def test_intention_requires_scope(self) -> None:
        with pytest.raises(Exception):
            Intention(action={"tool": "x"}, scope=[], expected_outcome="y")

    def test_conflict_requires_overlapping_intention(self) -> None:
        with pytest.raises(Exception):
            Conflict(intention_id="01HQ" + "0" * 22, conflicting_intentions=[], kind="scope_overlap")

    def test_belief_confidence_bounded(self) -> None:
        with pytest.raises(Exception):
            Belief(key="x", value=1, confidence=1.5, source="observed")
        with pytest.raises(Exception):
            Belief(key="x", value=1, confidence=-0.1, source="observed")

    def test_resolution_requires_error_on_failure(self) -> None:
        # Pydantic with our model lets this through; spec-level allOf if-then is JSON-Schema only.
        # This is a known gap: the JSON Schema enforces this, the Pydantic model does not.
        # Document the gap by asserting current behavior so we notice if it changes.
        r = Resolution(intention_id="01HQ" + "0" * 22, outcome="failure")
        assert r.error is None


class TestPayloadByTypeMap:
    def test_all_message_types_mapped(self) -> None:
        for mt in MessageType:
            assert mt in PAYLOAD_BY_TYPE
        assert len(PAYLOAD_BY_TYPE) == 8


class TestAgentRegistration:
    def test_capabilities_required(self) -> None:
        with pytest.raises(Exception):
            AgentRegistration(agent_id="a", session_id="s")  # type: ignore[call-arg]

    def test_minimal_valid_registration(self) -> None:
        reg = AgentRegistration(
            agent_id="a",
            session_id="s",
            capabilities=BackendCapabilities(
                backend_id="mock",
                tier="native",
                supports_midstream_inject=True,
            ),
        )
        assert reg.subscribes == []
        assert reg.scopes_owned == []
