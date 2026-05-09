"""Synapse MCP server — exposes audit pipeline as MCP tools.

This is the stdio-based MCP server (the standard for Claude Desktop /
Cursor / Continue / Cline). Implements the Model Context Protocol via a
hand-written JSON-RPC loop so we don't add the `mcp` package as a
required dep — everything Synapse-specific is in the slim install.

Protocol reference: https://spec.modelcontextprotocol.io
We implement the 2024-11-05 spec:
  - initialize / initialized
  - tools/list
  - tools/call

Five tools exposed:
  - audit_trace_file
  - find_conflicts_in_session
  - get_drift_score
  - list_supported_trace_formats
  - explain_conflict

Usage:
    python -m synapse.mcp.server
or as Claude Desktop MCP server:
    {"mcpServers": {"synapse": {"command": "python", "args": ["-m", "synapse.mcp.server"]}}}
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any, Optional


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "synapse"
SERVER_VERSION = "0.2.2"


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "audit_trace_file",
        "description": (
            "Run synapse audit on a trace file (OpenInference, LangSmith, "
            "Bedrock, Vertex, Azure, or JSONL). Returns the full AuditReport "
            "as JSON: events, conflicts, conflict_tiers, sas_pairs, "
            "estimated_wasted_tokens."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the trace file (.json, .jsonl, .ndjson)",
                },
                "lookback_seconds": {
                    "type": "integer",
                    "description": "Stale-base-overwrite window. Default 86400 (24h).",
                    "default": 86400,
                },
                "include_reads": {
                    "type": "boolean",
                    "description": "Include read-class tool calls (default false; reads can't collide).",
                    "default": False,
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "find_conflicts_in_session",
        "description": (
            "After audit_trace_file has run on a path, find all CONFLICT "
            "envelopes scoped to a specific session_id. Useful when one "
            "trace file contains multiple sessions and you only care about one."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["path", "session_id"],
        },
    },
    {
        "name": "get_drift_score",
        "description": (
            "Compute the SAS (Semantic Alignment Score) between two specific "
            "agents in a trace file. Returns SAS in [0, 1] plus the entity / "
            "action / temporal sub-scores. Low SAS = drift even without a "
            "hard CONFLICT firing yet."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "agent_a": {"type": "string"},
                "agent_b": {"type": "string"},
                "session_id": {
                    "type": "string",
                    "description": "Optional. If omitted, returns SAS across all sessions where both agents appear.",
                },
            },
            "required": ["path", "agent_a", "agent_b"],
        },
    },
    {
        "name": "list_supported_trace_formats",
        "description": (
            "Return the list of trace formats Synapse can audit. No arguments. "
            "Useful for an agent deciding whether to recommend Synapse for a "
            "given trace export."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "explain_conflict",
        "description": (
            "After audit_trace_file has run, return a plain-English explanation "
            "of conflict #N including: which agents collided, on which scope, "
            "the SCF resolution-tier hint (policy / capability / temporal), "
            "and the rationale string."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "conflict_index": {"type": "integer"},
            },
            "required": ["path", "conflict_index"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

# Minimal in-process cache so repeated `find_conflicts_in_session` /
# `explain_conflict` calls don't re-run the audit pipeline. Bounded
# to last 8 traces.
_AUDIT_CACHE: dict[str, Any] = {}
_AUDIT_CACHE_ORDER: list[str] = []
_CACHE_LOCK = threading.Lock()


def _cached_audit(path: str, lookback_ms: int = 86400_000, write_only: bool = True):
    from synapse.audit import audit_traces
    key = f"{path}|{lookback_ms}|{write_only}"
    with _CACHE_LOCK:
        if key in _AUDIT_CACHE:
            return _AUDIT_CACHE[key]
    rep = audit_traces(path, lookback_ms=lookback_ms, write_only=write_only)
    with _CACHE_LOCK:
        _AUDIT_CACHE[key] = rep
        _AUDIT_CACHE_ORDER.append(key)
        if len(_AUDIT_CACHE_ORDER) > 8:
            old = _AUDIT_CACHE_ORDER.pop(0)
            _AUDIT_CACHE.pop(old, None)
    return rep


def tool_audit_trace_file(args: dict) -> dict:
    path = args["path"]
    if not Path(path).exists():
        return {"error": f"file not found: {path}"}
    lookback_ms = int(args.get("lookback_seconds", 86400)) * 1000
    write_only = not args.get("include_reads", False)
    try:
        rep = _cached_audit(path, lookback_ms=lookback_ms, write_only=write_only)
        return rep.to_json_dict()
    except Exception as e:
        return {"error": f"audit failed: {type(e).__name__}: {e}"}


def tool_find_conflicts_in_session(args: dict) -> dict:
    rep = _cached_audit(args["path"])
    sess = args["session_id"]
    matches = [c.to_dict() for c in rep.conflicts if c.intention.session_id == sess]
    return {"session_id": sess, "n_conflicts": len(matches), "conflicts": matches}


def tool_get_drift_score(args: dict) -> dict:
    rep = _cached_audit(args["path"])
    a = args["agent_a"]
    b = args["agent_b"]
    sess = args.get("session_id")
    matches = []
    for p in rep.sas_pairs:
        if {p.agent_a, p.agent_b} != {a, b}:
            continue
        if sess and p.session_id != sess:
            continue
        matches.append(p.to_dict())
    if not matches:
        return {
            "error": f"no SAS pair found for agents={sorted([a, b])}"
                     + (f" in session={sess}" if sess else ""),
            "available_pairs": [
                {"agent_a": p.agent_a, "agent_b": p.agent_b, "session_id": p.session_id}
                for p in rep.sas_pairs
            ],
        }
    return {"matches": matches}


def tool_list_supported_trace_formats(args: dict) -> dict:
    return {
        "formats": [
            {"name": "openinference", "description": "OpenInference / OTel JSON spans (LangChain, LlamaIndex, OpenAI SDK, Anthropic SDK auto-instrumented)"},
            {"name": "langsmith",     "description": "LangSmith run exports"},
            {"name": "bedrock",       "description": "AWS Bedrock Agents trace export (inline trace field)"},
            {"name": "vertex",        "description": "GCP Vertex AI Agent Builder / ADK Cloud Trace export"},
            {"name": "azure",         "description": "Azure AI Agent Service / Application Insights export"},
            {"name": "jsonl",         "description": "Generic Synapse JSONL audit log"},
        ],
        "auto_detected": True,
        "note": "Pass any of these trace JSON files to audit_trace_file. Format is auto-detected.",
    }


def tool_explain_conflict(args: dict) -> dict:
    rep = _cached_audit(args["path"])
    idx = int(args["conflict_index"])
    if idx < 0 or idx >= len(rep.conflicts):
        return {"error": f"conflict_index {idx} out of range; total conflicts = {len(rep.conflicts)}"}
    c = rep.conflicts[idx]
    others = sorted({x.agent_id for x in c.conflicting})
    explanation = (
        f"Conflict #{idx}: {c.kind} on {c.overlapping_scopes}. "
        f"Agent {c.intention.agent_id} ({c.intention.tool_name} at "
        f"ts_ms={c.intention.ts_start_ms}) collided with prior writes by "
        f"{', '.join(others)}. SCF resolution tier: {c.resolution_tier_hint}. "
        f"Rationale: {c.rationale}"
    )
    return {
        "conflict_index": idx,
        "kind": c.kind,
        "scopes": c.overlapping_scopes,
        "intention_agent": c.intention.agent_id,
        "conflicting_agents": others,
        "resolution_tier_hint": c.resolution_tier_hint,
        "rationale": c.rationale,
        "explanation": explanation,
    }


TOOL_HANDLERS = {
    "audit_trace_file": tool_audit_trace_file,
    "find_conflicts_in_session": tool_find_conflicts_in_session,
    "get_drift_score": tool_get_drift_score,
    "list_supported_trace_formats": tool_list_supported_trace_formats,
    "explain_conflict": tool_explain_conflict,
}


# ---------------------------------------------------------------------------
# JSON-RPC over stdio (MCP transport)
# ---------------------------------------------------------------------------

def _send(msg: dict) -> None:
    line = json.dumps(msg, default=str)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _err(req_id: Any, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def _reply(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _handle(req: dict) -> Optional[dict]:
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params", {}) or {}

    if method == "initialize":
        return _reply(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })

    if method == "initialized":
        return None  # notification, no reply

    if method == "tools/list":
        return _reply(req_id, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {}) or {}
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            return _err(req_id, -32601, f"unknown tool: {name}")
        try:
            result = handler(args)
            return _reply(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}],
                "isError": "error" in result,
            })
        except Exception as e:
            return _err(req_id, -32000, f"tool error: {type(e).__name__}: {e}")

    if method in ("ping",):
        return _reply(req_id, {})

    if req_id is None:
        return None  # silently drop unknown notifications
    return _err(req_id, -32601, f"method not found: {method}")


def main() -> None:
    """Run the stdio MCP server."""
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            continue
        resp = _handle(req)
        if resp is not None:
            _send(resp)


if __name__ == "__main__":
    main()
