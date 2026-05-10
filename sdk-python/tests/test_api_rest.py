"""End-to-end tests for the Synapse REST API.

Drives every endpoint via httpx.AsyncClient against the FastAPI app
in zero-infra mode. Proves the contract a real HTTP client (curl,
Aider, Goose, Zed, ...) sees -- not just that imports succeed.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
async def _isolate(tmp_path, monkeypatch):
    """Fresh runtime per test, SQLite at tmp path, in-memory bus."""
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    monkeypatch.delenv("SYNAPSE_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("SYNAPSE_OFFLINE", raising=False)
    monkeypatch.setenv("SYNAPSE_SQLITE_PATH", str(tmp_path / "api.db"))
    from synapse.intend import shutdown as _sd
    await _sd()
    yield
    await _sd()


@pytest.fixture
async def client():
    from synapse.api.server import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


# ---------------------------------------------------------------------------
# Health + metadata
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_root_returns_html(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert "synapse api" in r.text.lower()
    assert "/docs" in r.text


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "uptime_s" in body


@pytest.mark.asyncio
async def test_version(client):
    r = await client.get("/version")
    assert r.status_code == 200
    body = r.json()
    assert "synapse_version" in body
    assert "frameworks_supported" in body
    # Must include the canonical 12-framework matrix
    for fw in ("langchain", "autogen", "crewai", "agno",
               "pydantic_ai", "llama_index", "google_adk", "otel"):
        assert fw in body["frameworks_supported"], (
            f"Expected {fw} in supported list, got {body['frameworks_supported']}"
        )


@pytest.mark.asyncio
async def test_list_frameworks(client):
    r = await client.get("/v1/frameworks")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 12
    assert "crewai" in body["supported"]


@pytest.mark.asyncio
async def test_openapi_docs_renders(client):
    """OpenAPI must render -- proves all endpoint schemas validate."""
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert schema["info"]["title"] == "Synapse REST API"
    paths = schema["paths"]
    # Spot-check the documented surface
    assert "/v1/intent" in paths
    assert "/v1/conflicts" in paths
    assert "/v1/beliefs" in paths
    assert "/v1/audit/jsonl" in paths


# ---------------------------------------------------------------------------
# Coordination — claim + resolve
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_intent_claim_and_resolve_no_conflict(client):
    r = await client.post("/v1/intent", json={
        "scope": ["repo.fs.api/test_a.py:w"],
        "agent": "alice",
        "session": "api_test_no_conflict",
        "expected_outcome": "test write",
        "blocking": True,
        "gate_ms": 50,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["intention_id"]
    assert body["has_conflicts"] is False
    assert body["conflicts"] == []

    # Resolve
    r2 = await client.post(
        f"/v1/intent/{body['intention_id']}/resolve",
        json={"outcome": "success", "state_diff": {"output_preview": "wrote 10 bytes"}},
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "resolved"

    # Idempotency: second resolve returns 404
    r3 = await client.post(
        f"/v1/intent/{body['intention_id']}/resolve",
        json={"outcome": "success"},
    )
    assert r3.status_code == 404


@pytest.mark.asyncio
async def test_intent_claim_then_session_intentions_listed(client):
    r = await client.post("/v1/intent", json={
        "scope": ["repo.fs.api/test_b.py:w"],
        "agent": "bob",
        "session": "api_listed",
        "blocking": False,
    })
    assert r.status_code == 200
    intent_id = r.json()["intention_id"]

    # Resolve so the next call doesn't hang
    await client.post(
        f"/v1/intent/{intent_id}/resolve",
        json={"outcome": "success"},
    )

    # Give the in-process router time to flush
    await asyncio.sleep(0.1)

    r2 = await client.get("/v1/sessions/api_listed/intentions")
    assert r2.status_code == 200
    intents = r2.json()["intentions"]
    assert any(i["agent_id"] == "bob" for i in intents), intents

    r3 = await client.get("/v1/sessions/api_listed/agents")
    assert r3.status_code == 200
    assert "bob" in r3.json()["agents"]


@pytest.mark.asyncio
async def test_intent_two_agents_collide(client):
    """Two parallel claim requests on the same scope. The second arriver
    must see a conflict in its response payload."""
    scope = ["repo.fs.shared/db.py:w"]
    sess = "api_collide"

    # Alice claims first; we DON'T resolve so it stays active
    ra = await client.post("/v1/intent", json={
        "scope": scope, "agent": "alice", "session": sess,
        "blocking": False,
    })
    assert ra.status_code == 200
    alice_id = ra.json()["intention_id"]

    # Bob arrives with a long enough gate to catch alice's active intent
    rb = await client.post("/v1/intent", json={
        "scope": scope, "agent": "bob", "session": sess,
        "blocking": True, "gate_ms": 200,
    })
    assert rb.status_code == 200
    body = rb.json()
    assert body["has_conflicts"] is True, (
        f"second arriver should see CONFLICT; got {body}"
    )
    # Conflict shape — at least one conflicting_intention should reference alice
    assert body["conflicts"], body
    cis = body["conflicts"][0].get("conflicting_intentions") or []
    assert any(ci.get("agent_id") == "alice" for ci in cis), cis

    # Cleanup
    await client.post(f"/v1/intent/{alice_id}/resolve", json={"outcome": "success"})
    await client.post(
        f"/v1/intent/{body['intention_id']}/resolve", json={"outcome": "success"},
    )


# ---------------------------------------------------------------------------
# Beliefs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_belief_endpoint_round_trips_through_state(client):
    sess = "api_belief"
    r1 = await client.post("/v1/beliefs", json={
        "agent": "alice", "session": sess,
        "key": "revenue_formula", "value": "qty * price",
        "confidence": 0.95, "source": "observed",
    })
    assert r1.status_code == 200
    body1 = r1.json()
    # Single-agent belief: no divergence yet
    assert body1["divergence"] is None

    # Bob disagrees -- divergence must surface
    r2 = await client.post("/v1/beliefs", json={
        "agent": "bob", "session": sess,
        "key": "revenue_formula", "value": "qty * price - discount",
        "confidence": 0.9, "source": "observed",
    })
    assert r2.status_code == 200
    div = r2.json()["divergence"]
    assert div is not None, "REST belief endpoint failed to surface divergence"
    assert div["key"] == "revenue_formula"

    # Listing endpoint
    r3 = await client.get(f"/v1/beliefs/divergences?session={sess}")
    assert r3.status_code == 200
    divs = r3.json()["divergences"]
    assert any(d["key"] == "revenue_formula" for d in divs)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audit_jsonl_inline(client):
    # Two synthetic events, one a write tool call so the auditor includes it
    body = "\n".join([
        json.dumps({
            "trace_id": "t", "span_id": "s1", "agent_id": "alice",
            "session_id": "audit_test",
            "tool_name": "edit_file",
            "tool_args": {"path": "x.py", "content": "a"},
            "ts_start_ms": 1000, "ts_end_ms": 1050,
        }),
        json.dumps({
            "trace_id": "t", "span_id": "s2", "agent_id": "bob",
            "session_id": "audit_test",
            "tool_name": "edit_file",
            "tool_args": {"path": "x.py", "content": "b"},
            "ts_start_ms": 1010, "ts_end_ms": 1060,
        }),
    ])
    r = await client.post(
        "/v1/audit/jsonl",
        content=body, headers={"content-type": "application/x-ndjson"},
    )
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["total_events"] >= 2
    # Both writers on the same path -> conflict expected
    assert rep["n_conflicts"] >= 1, rep


@pytest.mark.asyncio
async def test_audit_jsonl_empty_body_400(client):
    r = await client.post(
        "/v1/audit/jsonl", content="",
        headers={"content-type": "application/x-ndjson"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_audit_from_path_not_found(client):
    r = await client.post("/v1/audit/from-path", json={
        "path": "/tmp/synapse_does_not_exist.jsonl",
    })
    assert r.status_code == 404
