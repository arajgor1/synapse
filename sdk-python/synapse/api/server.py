"""Synapse REST API server.

A FastAPI surface that exposes Synapse's coordination + audit primitives
over HTTP so any agent, regardless of language or framework, can
participate in cross-agent collision detection. Closes the gap with
non-Python tools (Aider, Goose, Zed, Amazon Q, Roo Code, Kilo Code,
GitHub Copilot extensions, etc.) that can't import ``synapse-protocol``
but can speak HTTP.

Design principles
-----------------
* **Mirror the Python SDK 1:1** where it makes sense — every endpoint
  maps to a callable in ``synapse`` so the REST API can never drift
  beyond what the SDK actually does.
* **Zero-infra by default** — same as the SDK: if Redis/Postgres aren't
  configured, the API auto-engages in-memory bus + SQLite.
* **Stateless requests** — each request carries its own ``session_id``
  and ``agent`` in the body. No login / no sessions / no auth in core
  (auth is the user's reverse proxy's job — documented in API.md).
* **Stable shapes** — request + response models are pydantic; everything
  has explicit ``examples`` so the auto-generated OpenAPI docs are
  immediately useful.

Endpoint surface (see openapi at /docs once running)
-----------------------------------------------------
Health & metadata:
  GET  /                      — landing page (HTML)
  GET  /health                — liveness probe
  GET  /version               — synapse version + mode + frameworks loaded

Coordination (the hot path):
  POST /v1/intent             — claim a scope, returns conflicts if any
  POST /v1/intent/{id}/resolve — emit RESOLUTION
  GET  /v1/conflicts          — list conflicts in a session

Beliefs:
  POST /v1/beliefs            — emit a BELIEF, returns divergences
  GET  /v1/beliefs/divergences — list current divergences

Audit (existing trace exports):
  POST /v1/audit/jsonl        — POST a JSONL body, get a conflict report
  POST /v1/audit/from-path    — server-side path (when api lives next to traces)

State / observability:
  GET  /v1/sessions           — list active sessions
  GET  /v1/sessions/{id}/agents — agents in a session
  GET  /v1/sessions/{id}/intentions — intentions in a session

Live coordination:
  WS   /v1/stream             — WebSocket: live INTENTION + CONFLICT events

Run:
    pip install 'synapse-protocol[gateway]'
    synapse api                # zero-infra defaults
    synapse api --port 9000    # custom port
    synapse api --bind 0.0.0.0 # LAN-accessible (warns)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, AsyncIterator, Optional

try:
    from fastapi import (
        FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect,
    )
    from fastapi.responses import HTMLResponse, JSONResponse
    from pydantic import BaseModel, Field
    _FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    _FASTAPI_AVAILABLE = False
    raise ImportError(
        "synapse.api requires the [gateway] extras. "
        "Install with `pip install 'synapse-protocol[gateway]'`."
    )

import synapse
from synapse.audit.events import AuditEvent
from synapse.audit.scope_inference import infer_scope


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class IntentRequest(BaseModel):
    """POST /v1/intent — claim a scope and emit an INTENTION."""
    scope: list[str] = Field(
        ..., description="Scope strings, e.g. ['repo.fs.app/models.py:w']",
        examples=[["repo.fs.app/auth.py:w"]],
    )
    agent: str = Field(..., description="Agent identifier (race-free attribution)")
    session: str = Field(
        "default", description="Session ID — usually one per workflow / run",
    )
    expected_outcome: str = Field("", description="Human-readable description")
    blocking: bool = Field(True, description="If True, gate window catches CONFLICTs")
    gate_ms: int = Field(50, ge=0, le=10000)
    proposed_action: Optional[dict[str, Any]] = Field(
        None, description="Tool args; required for auto_merge policy"
    )
    merge_policy: Optional[str] = Field(
        None,
        description=(
            "Optional policy name: redirect / wait / abort / auto_merge / no_op / "
            "queue_behind / wait_for_other / work_on_different_scope / "
            "escalate_to_human / retry_with_backoff"
        ),
    )


class IntentResponse(BaseModel):
    """The server returns the intention id + any caught conflicts."""
    intention_id: str
    has_conflicts: bool
    conflicts: list[dict[str, Any]]
    rationale: Optional[str] = None
    merged_action: Optional[dict[str, Any]] = None


class ResolveRequest(BaseModel):
    outcome: str = Field("success", pattern="^(success|failure|skipped)$")
    state_diff: dict[str, Any] = Field(default_factory=dict)
    side_effects: list[str] = Field(default_factory=list)


class BeliefRequest(BaseModel):
    agent: str
    session: str = "default"
    key: str
    value: Any
    confidence: float = Field(0.9, ge=0.0, le=1.0)
    source: str = Field("observed", pattern="^(observed|inferred|assumed)$")
    evidence: Optional[str] = None


class BeliefResponse(BaseModel):
    belief_id: Optional[str] = None
    divergence: Optional[dict[str, Any]] = None


class AuditFromPathRequest(BaseModel):
    path: str = Field(..., description="Server-side trace file path")
    lookback_ms: int = Field(60_000, ge=0)
    include_reads: bool = False


# ---------------------------------------------------------------------------
# App + lifespan
# ---------------------------------------------------------------------------
_app_started_at = time.time()


# In-memory live-pending intentions awaiting RESOLUTION via REST.
# Maps intention_id -> IntentionHandle context. We keep the async-context
# entered until the caller hits POST /resolve, then exit it cleanly so
# RESOLUTION emits.
_pending_intents: dict[str, dict[str, Any]] = {}
_pending_lock = asyncio.Lock()


app = FastAPI(
    title="Synapse REST API",
    version=synapse.__version__,
    description=(
        "HTTP surface for Synapse's coordination + audit primitives. "
        "Lets non-Python agents (Aider, Goose, Zed, Amazon Q, Roo/Kilo Code, "
        "GitHub Copilot extensions, ...) participate in cross-agent collision "
        "detection. Mirrors the Python SDK 1:1."
    ),
    docs_url="/docs", redoc_url="/redoc",
)


# ---------------------------------------------------------------------------
# Health + metadata
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root() -> str:
    return f"""<!doctype html>
<html><head><title>synapse api</title>
<style>body{{font-family:-apple-system,system-ui,sans-serif;background:#0b0c10;color:#e8e8e8;
margin:0;padding:24px}}h1{{color:#66d9ef;margin:0 0 12px 0}}a{{color:#66d9ef}}
code{{background:#1a1d24;padding:2px 6px;border-radius:3px;font-size:13px}}
li{{margin:4px 0}}</style></head><body>
<h1>synapse api · v{synapse.__version__}</h1>
<p>HTTP surface for Synapse's coordination + audit primitives.</p>
<ul>
  <li><a href="/docs">/docs</a> — interactive OpenAPI (Swagger)</li>
  <li><a href="/redoc">/redoc</a> — alternative API browser</li>
  <li><a href="/health">/health</a> — liveness probe</li>
  <li><a href="/version">/version</a> — version + mode + loaded frameworks</li>
</ul>
<p>Quickstart:</p>
<pre><code>curl -X POST http://localhost:8000/v1/intent \\
  -H 'content-type: application/json' \\
  -d '{{"scope":["repo.fs.foo:w"],"agent":"alice","session":"demo"}}'</code></pre>
</body></html>"""


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "uptime_s": round(time.time() - _app_started_at, 1)}


@app.get("/version")
async def version() -> dict[str, Any]:
    from synapse.intend import _runtime
    from synapse.install import _FRAMEWORK_REGISTRY
    return {
        "synapse_version": synapse.__version__,
        "api_uptime_s": round(time.time() - _app_started_at, 1),
        "mode": _runtime.get("mode", "unknown"),
        "state_backend": _runtime.get("state_backend"),
        "frameworks_supported": list(_KNOWN_FRAMEWORKS),
        "frameworks_loaded": sorted(_FRAMEWORK_REGISTRY.keys()),
    }


# Canonical list of frameworks the SDK ships an adapter for. The
# registry-based view in /v1/frameworks reflects what's actually loaded;
# this list reflects what's _available_ even before any install() call.
_KNOWN_FRAMEWORKS = (
    "langchain", "langgraph", "autogen", "smolagents", "crewai",
    "openai_agents", "pydantic_ai", "agno", "llama_index", "google_adk",
    "hermes", "otel",
)


@app.get("/v1/frameworks")
async def list_frameworks() -> dict[str, Any]:
    """Return the list of framework adapters Synapse ships."""
    from synapse.install import _FRAMEWORK_REGISTRY
    loaded = sorted(_FRAMEWORK_REGISTRY.keys())
    return {
        "supported": list(_KNOWN_FRAMEWORKS),
        "loaded_in_this_process": loaded,
        "count": len(_KNOWN_FRAMEWORKS),
    }


# ---------------------------------------------------------------------------
# Coordination: claim → resolve
# ---------------------------------------------------------------------------

@app.post("/v1/intent", response_model=IntentResponse)
async def claim_intent(req: IntentRequest) -> IntentResponse:
    """Emit an INTENTION + return any caught CONFLICTs.

    The intention stays ACTIVE until the caller hits ``POST /v1/intent/{id}/resolve``
    (or the API process restarts). This matches the SDK semantics — the
    body of an ``async with synapse.intend(...)`` block is "the request
    holds the claim until it explicitly releases".
    """
    handle_state: dict[str, Any] = {}

    async def _hold():
        """Enter the intend() context, stash the handle, wait for release."""
        from synapse.policies.registry import resolve_policy
        policy = resolve_policy(req.merge_policy) if req.merge_policy else None
        with synapse.with_agent(req.agent):
            async with synapse.intend(
                scope=req.scope,
                agent=req.agent,
                session=req.session,
                expected_outcome=req.expected_outcome,
                blocking=req.blocking,
                gate_ms=req.gate_ms,
                proposed_action=req.proposed_action,
                merge_policy=policy,
            ) as i:
                handle_state["intention_id"] = i.intention_id
                handle_state["conflicts"] = list(i.conflicts) if i.conflicts else []
                handle_state["merged_action"] = i.merged_action
                handle_state["policy_rationale"] = i.policy_rationale
                handle_state["release_event"] = asyncio.Event()
                handle_state["resolution"] = None
                handle_state["handle"] = i

                # Park here until POST /resolve fires release_event
                await handle_state["release_event"].wait()

                # Apply the resolution payload (if any) before exiting
                resolution = handle_state.get("resolution") or {}
                state_diff = resolution.get("state_diff") or {}
                if state_diff:
                    i.set_state_diff(state_diff)
                if resolution.get("outcome") == "failure":
                    i.mark_failed(resolution.get("error") or "REST resolve(outcome=failure)")
                for eff in resolution.get("side_effects") or []:
                    i.add_side_effect(eff)

    # Run _hold as a background task; wait until handle_state is populated.
    task = asyncio.create_task(_hold(), name=f"synapse.api.intent:{req.agent}:{req.session}")
    # Wait briefly for the inner enter to populate handle_state
    deadline = time.monotonic() + max(req.gate_ms / 1000.0 + 1.0, 2.0)
    while "intention_id" not in handle_state and time.monotonic() < deadline:
        if task.done():
            # Task crashed before entering — surface the error
            try:
                task.result()
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"intent failed: {e}")
            break
        await asyncio.sleep(0.005)

    if "intention_id" not in handle_state:
        # Timed out before the SDK populated the handle — most likely a
        # synapse runtime hang. Cancel and report.
        task.cancel()
        raise HTTPException(status_code=504, detail="synapse.intend did not enter within deadline")

    intent_id = handle_state["intention_id"]
    async with _pending_lock:
        _pending_intents[intent_id] = {
            "task": task,
            "state": handle_state,
            "agent": req.agent,
            "session": req.session,
        }

    conflicts_dict = [
        c.model_dump() if hasattr(c, "model_dump") else dict(c)
        for c in handle_state["conflicts"]
    ]
    return IntentResponse(
        intention_id=intent_id,
        has_conflicts=bool(conflicts_dict),
        conflicts=conflicts_dict,
        rationale=handle_state.get("policy_rationale"),
        merged_action=handle_state.get("merged_action"),
    )


@app.post("/v1/intent/{intention_id}/resolve")
async def resolve_intent(
    intention_id: str, req: ResolveRequest,
) -> dict[str, Any]:
    """Release the parked intent. Emits a RESOLUTION envelope under the
    hood. Idempotent — second call on the same id returns 404 (already
    resolved + cleaned up)."""
    async with _pending_lock:
        slot = _pending_intents.pop(intention_id, None)
    if slot is None:
        raise HTTPException(
            status_code=404,
            detail=f"intention {intention_id} not pending (already resolved or unknown)",
        )

    state = slot["state"]
    state["resolution"] = req.model_dump()
    state["release_event"].set()

    # Wait briefly for the SDK's exit-block to emit RESOLUTION
    try:
        await asyncio.wait_for(slot["task"], timeout=5.0)
    except asyncio.TimeoutError:
        slot["task"].cancel()
        return {"intention_id": intention_id, "status": "timeout_during_resolve"}
    except Exception as e:
        return {"intention_id": intention_id, "status": "error", "error": str(e)}
    return {"intention_id": intention_id, "status": "resolved", **req.model_dump()}


# ---------------------------------------------------------------------------
# Conflicts query
# ---------------------------------------------------------------------------

@app.get("/v1/conflicts")
async def list_conflicts(
    session: str, lookback_ms: int = 60_000,
) -> dict[str, Any]:
    """Return active + recently-resolved conflicts in this session."""
    from synapse.intend import _ensure_connected
    rt = await _ensure_connected()
    state = rt.get("state")
    if state is None:
        return {"session": session, "conflicts": [], "mode": rt.get("mode")}

    # Probe by querying for ANY active intention overlapping a never-match
    # scope to get the active set indirectly; cleaner is to add a dedicated
    # state method, but for v0.2.4 we pull the active intentions list and
    # match pairs in Python.
    if hasattr(state, "intentions_active_in"):
        # We don't have a "list all active" method yet — synthesise one
        # via SQL. For now use find_conflicts with a sentinel that catches
        # nothing; the empty result lists actives from rows in the WHERE.
        # Cleaner: dedicated method. Adding below.
        pass

    actives = await _list_active_intentions(state, session)
    return {"session": session, "active_intentions": actives}


async def _list_active_intentions(state: Any, session_id: str) -> list[dict]:
    """Backend-agnostic 'list active intentions in session'."""
    # Both backends know how to enumerate; we add a small adapter here
    # rather than threading another method through every state graph.
    try:
        # SQLite path
        from synapse.state_sqlite import SqliteStateGraph
        if isinstance(state, SqliteStateGraph):
            rows = await state._fetchall(
                "SELECT id, agent_id, scope, expected_outcome, created_at "
                "FROM intentions WHERE session_id = ? AND status = 'active' "
                "ORDER BY created_at",
                (session_id,),
            )
            return [
                {
                    "intention_id": r[0], "agent_id": r[1],
                    "scope": json.loads(r[2]) if isinstance(r[2], str) else r[2],
                    "expected_outcome": r[3], "ts_ms": int((r[4] or 0) * 1000),
                }
                for r in rows
            ]
    except Exception as e:
        logger.warning("list_active_intentions sqlite path failed (%s)", e)

    # Postgres path
    try:
        async with state.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, agent_id, scope, expected_outcome, "
                "EXTRACT(EPOCH FROM created_at)*1000 AS ts_ms "
                "FROM intentions WHERE session_id = $1 AND status = 'active' "
                "ORDER BY created_at",
                session_id,
            )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("list_active_intentions postgres path failed (%s)", e)
        return []


# ---------------------------------------------------------------------------
# Beliefs
# ---------------------------------------------------------------------------

@app.post("/v1/beliefs", response_model=BeliefResponse)
async def emit_belief_endpoint(req: BeliefRequest) -> BeliefResponse:
    div = await synapse.emit_belief(
        agent=req.agent, session=req.session,
        key=req.key, value=req.value,
        confidence=req.confidence, source=req.source,
        evidence=req.evidence, detect_divergence=True,
    )
    div_payload = None
    if div is not None:
        div_payload = div.to_dict() if hasattr(div, "to_dict") else dict(div)
    return BeliefResponse(divergence=div_payload)


@app.get("/v1/beliefs/divergences")
async def list_belief_divergences(session: str) -> dict[str, Any]:
    divs = await synapse.list_divergences(session_id=session)
    out = []
    for d in divs:
        if hasattr(d, "to_dict"):
            out.append(d.to_dict())
        elif hasattr(d, "model_dump"):
            out.append(d.model_dump())
        else:
            out.append(dict(d))
    return {"session": session, "divergences": out}


# ---------------------------------------------------------------------------
# Audit (existing trace exports)
# ---------------------------------------------------------------------------

@app.post("/v1/audit/jsonl")
async def audit_jsonl(request: Request) -> dict[str, Any]:
    """POST a JSONL body (one event per line). Returns a conflict report."""
    body = (await request.body()).decode("utf-8", errors="ignore")
    if not body.strip():
        raise HTTPException(status_code=400, detail="empty body")

    import tempfile
    from synapse.audit.pipeline import audit_traces
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8",
    ) as f:
        f.write(body)
        tmp_path = f.name
    try:
        rep = audit_traces(tmp_path)
        return _report_to_dict(rep)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@app.post("/v1/audit/from-path")
async def audit_from_path(req: AuditFromPathRequest) -> dict[str, Any]:
    """Audit a trace file already on the server's filesystem."""
    if not os.path.exists(req.path):
        raise HTTPException(status_code=404, detail=f"path not found: {req.path}")
    from synapse.audit.pipeline import audit_traces
    rep = audit_traces(req.path, lookback_ms=req.lookback_ms,
                       include_reads=req.include_reads)
    return _report_to_dict(rep)


def _report_to_dict(rep: Any) -> dict[str, Any]:
    """Coerce an AuditReport to a JSON-serialisable dict."""
    out = {
        "total_events": getattr(rep, "total_events", 0),
        "n_conflicts": len(getattr(rep, "conflicts", []) or []),
        "n_sas_pairs": len(getattr(rep, "sas_pairs", []) or []),
        "conflicts": [],
        "sas_pairs": [],
    }
    for c in getattr(rep, "conflicts", []) or []:
        out["conflicts"].append({
            "kind": getattr(c, "kind", None),
            "overlapping_scopes": list(getattr(c, "overlapping_scopes", []) or []),
            "intention_agent": getattr(getattr(c, "intention", None), "agent_id", None),
            "conflicting_agents": [
                getattr(x, "agent_id", None)
                for x in (getattr(c, "conflicting", []) or [])
            ],
            "rationale": getattr(c, "rationale", None),
            "tier": getattr(c, "resolution_tier_hint", None),
        })
    for p in getattr(rep, "sas_pairs", []) or []:
        out["sas_pairs"].append({
            "agent_a": getattr(p, "agent_a", None),
            "agent_b": getattr(p, "agent_b", None),
            "sas": getattr(p, "sas", None),
            "shared_scopes": list(getattr(p, "shared_scopes", []) or []),
        })
    return out


# ---------------------------------------------------------------------------
# Sessions / observability
# ---------------------------------------------------------------------------

@app.get("/v1/sessions/{session}/intentions")
async def session_intentions(session: str) -> dict[str, Any]:
    from synapse.intend import _ensure_connected
    rt = await _ensure_connected()
    state = rt.get("state")
    if state is None:
        return {"session": session, "intentions": [], "mode": rt.get("mode")}
    # Re-use _list_active_intentions but include resolved too
    try:
        from synapse.state_sqlite import SqliteStateGraph
        if isinstance(state, SqliteStateGraph):
            rows = await state._fetchall(
                "SELECT id, agent_id, scope, status, expected_outcome, created_at "
                "FROM intentions WHERE session_id = ? ORDER BY created_at DESC",
                (session,),
            )
            return {"session": session, "intentions": [
                {"intention_id": r[0], "agent_id": r[1],
                 "scope": json.loads(r[2]) if isinstance(r[2], str) else r[2],
                 "status": r[3], "expected_outcome": r[4],
                 "ts_ms": int((r[5] or 0) * 1000)}
                for r in rows
            ]}
    except Exception:
        pass
    try:
        async with state.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, agent_id, scope, status, expected_outcome, "
                "EXTRACT(EPOCH FROM created_at)*1000 AS ts_ms "
                "FROM intentions WHERE session_id = $1 "
                "ORDER BY created_at DESC",
                session,
            )
        return {"session": session, "intentions": [dict(r) for r in rows]}
    except Exception as e:
        return {"session": session, "intentions": [], "error": str(e)}


@app.get("/v1/sessions/{session}/agents")
async def session_agents(session: str) -> dict[str, Any]:
    """Distinct agents observed in this session via persisted intentions."""
    res = await session_intentions(session)
    agents = sorted({i["agent_id"] for i in res.get("intentions", []) if i.get("agent_id")})
    return {"session": session, "agents": agents}


# ---------------------------------------------------------------------------
# WebSocket live stream
# ---------------------------------------------------------------------------

@app.websocket("/v1/stream")
async def ws_stream(ws: WebSocket) -> None:
    """Stream live INTENTION + CONFLICT events as they hit the JSONL audit
    log (tailed in real time). The client must set ``SYNAPSE_AUDIT_LOG``
    in the agent process so emits land in the file we tail.

    Filter via query param ``?session=<id>`` to only see one session.
    """
    await ws.accept()
    session_filter = ws.query_params.get("session")
    log_path = os.environ.get("SYNAPSE_AUDIT_LOG")
    if not log_path:
        await ws.send_text(json.dumps({
            "type": "error",
            "message": "SYNAPSE_AUDIT_LOG not configured on the server",
        }))
        await ws.close()
        return

    from synapse.streaming.server import _tail_jsonl
    import threading
    stop = threading.Event()
    try:
        # Run the blocking tail in a thread; bridge events into the WS via queue
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue(maxsize=200)

        def _drain():
            try:
                from pathlib import Path
                for _offset, ev in _tail_jsonl(Path(log_path), stop=stop):
                    if ev is None:
                        continue
                    if session_filter and ev.get("session_id") != session_filter:
                        continue
                    asyncio.run_coroutine_threadsafe(q.put(ev), loop)
            except Exception as e:
                logger.warning("ws_stream tail crashed (%s)", e)

        t = threading.Thread(target=_drain, daemon=True, name="synapse.api.ws-tail")
        t.start()
        while True:
            ev = await q.get()
            await ws.send_text(json.dumps(ev, default=str))
    except WebSocketDisconnect:
        pass
    finally:
        stop.set()


# ---------------------------------------------------------------------------
# CLI entry point — `synapse api`
# ---------------------------------------------------------------------------

def serve(
    *, host: str = "127.0.0.1", port: int = 8000, log_level: str = "info",
) -> None:
    """Launch the server with uvicorn. Used by the `synapse api` CLI."""
    import uvicorn
    print(f"  synapse api -- v{synapse.__version__}", flush=True)
    print(f"  bind   : {host}:{port}", flush=True)
    if host == "0.0.0.0":
        print("           WARNING: LAN-accessible. Anyone on this network can", flush=True)
        print("                    read or claim coordination state.", flush=True)
    print(f"  docs   : http://{host}:{port}/docs", flush=True)
    print(f"  health : http://{host}:{port}/health", flush=True)
    uvicorn.run(app, host=host, port=port, log_level=log_level)
