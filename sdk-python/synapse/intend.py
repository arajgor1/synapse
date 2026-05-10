"""``synapse.intend()`` — the universal context-manager SDK.

Wraps a tool dispatch with INTENTION emission, conflict detection, and
RESOLUTION on exit. Works in any Python codebase regardless of which
agent framework is in use; framework-specific adapters (LangGraph,
CrewAI, AutoGen, etc.) all use this internally.

Example:

    import synapse

    async with synapse.intend(
        scope=["repo.fs.auth.py:w"],
        agent="code-reviewer",
        expected_outcome="fix CVE-2026-1234",
    ) as i:
        if i.has_conflicts:
            # caller decides: redirect (re-prompt LLM with other agent's
            # work), wait, abort, or proceed anyway
            await i.pivot()
        result = await my_tool_call()
        i.set_state_diff({"lines_changed": 47})
    # RESOLUTION emitted automatically on exit (success or failure)
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Optional

from synapse.agent import Agent
from synapse.messages import Conflict

logger = logging.getLogger(__name__)


@dataclass
class IntentionHandle:
    """Returned from ``synapse.intend(...)``. Lets the caller inspect
    detected conflicts and choose how to react.
    """
    intention_id: str
    scope: list[str]
    agent_id: str
    session_id: str
    conflicts: list[Conflict] = field(default_factory=list)

    # Mutable: the caller fills these during the with-block
    state_diff: dict[str, Any] = field(default_factory=dict)
    side_effects: list[str] = field(default_factory=list)
    outcome: str = "success"
    error_message: Optional[str] = None

    # v0.2 week 4: filled in by AutoMergePolicy when it succeeds. The
    # caller should use ``merged_action`` instead of their original
    # tool args / content.
    merged_action: Optional[dict[str, Any]] = None
    # The MergePolicy's rationale string (logged + surfaced in resolution)
    policy_rationale: Optional[str] = None
    # Set when a policy decides ABORT (the caller's framework handles it)
    aborted: bool = False

    # v0.2 week 5: filled by the BELIEF auto-extractor (if enabled) and
    # the live divergence detector. divergences is a list of
    # LiveDivergenceResult dicts when emitted beliefs disagreed with
    # other agents' prior beliefs.
    beliefs_emitted: list[dict[str, Any]] = field(default_factory=list)
    divergences: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_conflicts(self) -> bool:
        return len(self.conflicts) > 0

    def set_state_diff(self, diff: dict[str, Any]) -> None:
        self.state_diff.update(diff)

    def add_side_effect(self, effect: str) -> None:
        self.side_effects.append(effect)

    def mark_failed(self, message: str = "") -> None:
        """Mark this intention as failed (RESOLUTION will record outcome=failure)."""
        self.outcome = "failure"
        self.error_message = message[:200] if message else None


# ---------------------------------------------------------------------------
# Module-level runtime: lazy bus + state graph + per-(session,agent) Agent cache
# ---------------------------------------------------------------------------
_runtime: dict[str, Any] = {}


def _get_or_init_runtime(
    *,
    bus_url: Optional[str] = None,
    state_dsn: Optional[str] = None,
) -> dict[str, Any]:
    """Idempotent runtime setup. ``synapse.install()`` configures this
    explicitly; ``intend()`` falls back to env vars if not.

    Three modes:
      * **live** — Redis + Postgres (or just Redis); user provided
        ``SYNAPSE_REDIS_URL`` or passed ``bus_url=``. Multi-process
        coordination via Redis Streams.
      * **zero-infra** — no Redis URL, no Postgres DSN. Single-process
        coordination via in-memory bus + SQLite state file at
        ``~/.synapse/state.db``. An in-process Router is auto-spawned
        on first connect so CONFLICTs flow back to agent inboxes
        without the user starting a separate worker.
      * **offline** — explicitly disabled via ``SYNAPSE_OFFLINE=1`` or by
        passing ``zero_infra=False`` and providing no infra. ``intend()``
        becomes a recording no-op.
    """
    if _runtime.get("bus") is not None:
        return _runtime

    bus_url = bus_url or os.environ.get("SYNAPSE_REDIS_URL")
    state_dsn = state_dsn or os.environ.get("SYNAPSE_POSTGRES_DSN")

    # Explicit opt-out preserves the historical "no infra → no coordination"
    # behaviour for users who want it.
    if os.environ.get("SYNAPSE_OFFLINE") in ("1", "true", "True"):
        _runtime["mode"] = "offline"
        return _runtime

    if not bus_url:
        # Zero-infra path — auto-spin in-memory bus + SQLite. Default sqlite
        # path ~/.synapse/state.db can be overridden via SYNAPSE_SQLITE_PATH.
        from synapse.bus_inmemory import InMemoryBus

        _runtime["bus"] = InMemoryBus()
        _runtime["bus_url"] = "inmemory://"
        _runtime["state_dsn"] = (
            state_dsn or os.environ.get("SYNAPSE_SQLITE_PATH") or None
        )
        _runtime["state_backend"] = "sqlite"
        _runtime["agents"] = {}
        _runtime["mode"] = "zero-infra"
        _runtime["connected"] = False
        logger.info(
            "synapse: zero-infra mode (in-memory bus + SQLite state). "
            "Single-process only — set SYNAPSE_REDIS_URL for multi-process "
            "coordination."
        )
        return _runtime

    from synapse.bus import Bus

    _runtime["bus"] = Bus(bus_url)
    _runtime["bus_url"] = bus_url
    _runtime["state_dsn"] = state_dsn
    _runtime["state_backend"] = "postgres"
    _runtime["agents"] = {}
    _runtime["mode"] = "live"
    _runtime["connected"] = False
    return _runtime


async def _ensure_connected() -> dict[str, Any]:
    rt = _get_or_init_runtime()
    if rt.get("mode") == "offline":
        return rt
    if rt.get("connected"):
        return rt

    # Record the loop owning the bus + state pools so sync-bridge wrappers
    # can route back to it instead of running on the bridge loop (which
    # produces 'attached to a different loop' errors with asyncpg).
    try:
        rt["install_loop"] = asyncio.get_running_loop()
    except RuntimeError:
        rt["install_loop"] = None
    bus = rt["bus"]
    await bus.connect()

    state_backend = rt.get("state_backend")
    state_dsn = rt.get("state_dsn")
    if state_backend == "sqlite":
        # Zero-infra: SQLite is mandatory — that's where intentions live.
        from synapse.state_sqlite import SqliteStateGraph
        state = SqliteStateGraph(state_dsn)
        await state.connect()
        rt["state"] = state
    elif state_dsn:
        from synapse.state import StateGraph
        state = StateGraph(state_dsn)
        await state.connect()
        rt["state"] = state

    # Auto-spawn an in-process Router for zero-infra mode so CONFLICTs
    # actually flow back to agent inboxes. In live mode the user runs the
    # router as a separate process (`python -m synapse.runtime.router.worker`).
    if rt.get("mode") == "zero-infra" and rt.get("state") is not None:
        await _start_inprocess_router(rt)

    rt["connected"] = True
    return rt


async def _start_inprocess_router(rt: dict[str, Any]) -> None:
    """Initialise the per-session router registry for zero-infra mode.

    Routers themselves are spawned lazily in ``_get_agent`` once we know
    which session(s) to watch. This call just installs the registry slot.
    """
    rt.setdefault("_routers", {})  # session_id -> InProcessRouter


async def _ensure_router_for_session(rt: dict[str, Any], session_id: str) -> None:
    """Spawn the in-process L2 router for ``session_id`` if not already running.

    Only meaningful in zero-infra mode; in live mode the router runs as a
    separate process that the user starts (`python -m synapse.router_inprocess
    is NOT what they invoke — they run runtime/router/worker.py).
    """
    if rt.get("mode") != "zero-infra":
        return
    routers = rt.setdefault("_routers", {})
    if session_id in routers:
        return
    bus = rt.get("bus")
    state = rt.get("state")
    if bus is None or state is None:
        return
    from synapse.router_inprocess import InProcessRouter
    r = InProcessRouter(bus=bus, state=state, session_id=session_id)
    r.start()
    routers[session_id] = r
    logger.info(
        "synapse.router: in-process router started for session=%s "
        "(zero-infra mode)", session_id,
    )


async def _get_agent(agent_id: str, session_id: str) -> Optional[Agent]:
    """Return (and cache) a Synapse Agent for the given (agent_id, session_id).

    In offline mode (no bus configured), returns None — the caller treats
    intend() as a recording no-op.
    """
    rt = await _ensure_connected()
    if rt.get("mode") == "offline":
        return None

    cache_key = f"{session_id}::{agent_id}"
    agents = rt.setdefault("agents", {})
    if cache_key in agents:
        return agents[cache_key]

    from synapse.adapters.mock import MockAdapter

    agent = Agent(
        id=agent_id,
        session=session_id,
        backend=MockAdapter(),
        bus=rt["bus"],
        state=rt.get("state"),
        subscribes=[],
    )
    await agent._connect()
    if rt.get("state") is not None:
        await agent._register()
    agents[cache_key] = agent

    # Zero-infra mode: ensure the in-process L2 router is running for
    # this session so CONFLICTs flow back to inboxes. No-op in live mode.
    await _ensure_router_for_session(rt, session_id)

    return agent


# ---------------------------------------------------------------------------
# The main entry point — async context manager
# ---------------------------------------------------------------------------
@asynccontextmanager
async def intend(
    *,
    scope: list[str],
    agent: str,
    session: Optional[str] = None,
    expected_outcome: str = "",
    blocking: bool = True,
    gate_ms: int = 50,
    estimated_duration_ms: Optional[int] = None,
    uncertainty: Optional[str] = None,
    merge_policy: Any = None,                # v0.2-w4: MergePolicy | str | None
    critical_scopes: Optional[list[str]] = None,
    proposed_action: Optional[dict[str, Any]] = None,
):
    """Wrap a tool dispatch with Synapse coordination.

    On enter:
      - Emit INTENTION with the given scope
      - Optionally drain inbox for CONFLICT signals (gate window)
      - If conflicts found, run the configured ``merge_policy``:
          * critical_scopes match  → force ABORT (raises SynapseConflict)
          * MergePolicy.abort      → raise SynapseConflict
          * MergePolicy.wait       → block briefly + retry
          * MergePolicy.auto_merge → call user's LLM, fill handle.merged_action
          * MergePolicy.redirect   → log rationale, set handle.policy_rationale
      - Yield IntentionHandle so the caller can inspect + record state_diff

    On exit:
      - Emit RESOLUTION with the outcome (success / failure)

    Args:
        merge_policy: a ``synapse.MergePolicy.*`` constant, a custom
            MergePolicy instance, a string name ("redirect"/"wait"/...),
            or None to fall back to ``install()``-time default + a final
            fallback of redirect.
        critical_scopes: glob patterns. If any matches a scope on a
            CONFLICT-bearing intention, force ABORT regardless of policy.
        proposed_action: required for ``auto_merge`` — the tool args /
            content the agent is about to use. Optional otherwise.

    Offline mode (no bus): body still runs, no envelopes emitted, no
    policy applied (no conflicts can fire).
    """
    from synapse.policies import resolve_policy
    from synapse.policies.base import MergeDecision, SynapseConflict
    from synapse.policies.critical import (
        critical_scope_match, normalize_critical_scopes,
    )

    session_id = (
        session
        or os.environ.get("SYNAPSE_SESSION_ID")
        or "default_session"
    )

    handle = IntentionHandle(
        intention_id="",
        scope=list(scope),
        agent_id=agent,
        session_id=session_id,
    )

    # Resolve effective policy + critical_scopes from caller > install-time > defaults
    install_defaults = _runtime.get("policy_defaults") or {}
    policy = resolve_policy(merge_policy)
    if policy is None:
        policy = resolve_policy(install_defaults.get("merge_policy"))
    crit_scopes = normalize_critical_scopes(
        critical_scopes if critical_scopes is not None
        else install_defaults.get("critical_scopes")
    )

    syn_agent = None
    try:
        syn_agent = await _get_agent(agent, session_id)
    except Exception as e:
        logger.warning("synapse.intend: failed to set up agent (%s); offline mode", e)

    if syn_agent is not None:
        try:
            intention_id, conflicts = await syn_agent.emit_intention(
                action={"description": expected_outcome or f"intend:{agent}"},
                scope=list(scope),
                expected_outcome=expected_outcome or "tool dispatch",
                blocking=blocking,
                gate_ms=gate_ms,
                **({"estimated_duration_ms": estimated_duration_ms}
                   if estimated_duration_ms is not None else {}),
                **({"uncertainty": uncertainty} if uncertainty is not None else {}),
            )
            handle.intention_id = intention_id
            handle.conflicts = conflicts or []
        except Exception as e:
            logger.warning("synapse.intend: emit_intention failed (%s); proceeding anyway", e)

    # JSONL audit append — used by `synapse watch` to power the live
    # dashboard. Cheap append; no-op when SYNAPSE_AUDIT_LOG is unset.
    if _jsonl_audit_path():
        ts_now_ms = int(time.time() * 1000)
        _append_audit_jsonl({
            "type": "intention",
            "intention_id": handle.intention_id,
            "agent_id": agent,
            "session_id": session_id,
            "tool_name": expected_outcome or "intend",
            "tool_args": proposed_action or {},
            "scope": list(scope),
            "ts_start_ms": ts_now_ms,
            "ts_end_ms": ts_now_ms,
            "blocking": blocking,
            "n_conflicts_at_emit": len(handle.conflicts),
        })
        # If the gate window saw conflicts, surface them as separate
        # records so the streaming server's incremental detector and the
        # dashboard pick them up.
        for c in handle.conflicts:
            _append_audit_jsonl({
                "type": "conflict",
                "intention_id": handle.intention_id,
                "intention_agent": agent,
                "kind": getattr(c, "kind", "scope_overlap"),
                "scopes": list(getattr(c, "overlapping_scopes", scope)),
                "conflicting_agents": [
                    ci.agent_id for ci in getattr(c, "conflicting_intentions", [])
                ],
                "ts_ms": ts_now_ms,
                "rationale": getattr(c, "rationale", "")[:200],
            })

    # Apply MergePolicy if conflicts surfaced
    if handle.has_conflicts:
        # 1. critical_scopes hard-block first
        match = critical_scope_match(handle.scope, crit_scopes)
        if match:
            rationale = (
                f"Critical scope match: {match!r} forced ABORT on {handle.scope}. "
                f"{len(handle.conflicts)} conflicting intention(s)."
            )
            handle.aborted = True
            handle.policy_rationale = rationale
            handle.mark_failed(rationale)
            if syn_agent is not None and handle.intention_id:
                try:
                    await syn_agent.emit_resolution(
                        intention_id=handle.intention_id,
                        outcome="failure",
                        state_diff={"error": rationale, "policy": "critical_scope"},
                    )
                except Exception:
                    pass
            raise SynapseConflict(handle.conflicts, handle.scope, rationale)

        # 2. configured policy
        if policy is not None:
            try:
                action = await policy.resolve(handle, handle.conflicts, proposed_action)
            except Exception as e:
                logger.warning("synapse.intend: merge_policy.resolve raised (%s); proceeding", e)
                action = None
            if action is not None:
                handle.policy_rationale = action.rationale
                if action.decision == MergeDecision.ABORT:
                    handle.aborted = True
                    handle.mark_failed(action.rationale)
                    if syn_agent is not None and handle.intention_id:
                        try:
                            await syn_agent.emit_resolution(
                                intention_id=handle.intention_id,
                                outcome="failure",
                                state_diff={"error": action.rationale, "policy": policy.name},
                            )
                        except Exception:
                            pass
                    raise SynapseConflict(handle.conflicts, handle.scope, action.rationale)
                elif action.decision == MergeDecision.MERGED:
                    handle.merged_action = action.merged_action
                elif action.decision == MergeDecision.WAIT:
                    # Best-effort: sleep the timeout, then proceed.
                    # A full implementation would re-poll the state graph.
                    await asyncio.sleep(action.wait_timeout_ms / 1000)
                # MergeDecision.PROCEED needs no action

    started = time.time()
    try:
        yield handle
    except Exception as e:
        handle.mark_failed(str(e))
        raise
    finally:
        if syn_agent is not None and handle.intention_id and not handle.aborted:
            try:
                sd = handle.state_diff or (
                    {"error": handle.error_message} if handle.error_message else {}
                )
                if handle.policy_rationale:
                    sd = {**sd, "policy_rationale": handle.policy_rationale}
                await syn_agent.emit_resolution(
                    intention_id=handle.intention_id,
                    outcome=handle.outcome,
                    state_diff=sd,
                    side_effects=handle.side_effects or None,
                )
            except Exception as e:
                logger.warning("synapse.intend: emit_resolution failed (%s)", e)

        # v0.2 week 5: auto-extract BELIEFs from the tool's state_diff
        # and run live divergence detection. Opt-in via
        # synapse.install(emit_beliefs_from_tool_results=True).
        if (
            install_defaults.get("emit_beliefs_from_tool_results")
            and not handle.aborted
            and handle.outcome == "success"
            and handle.state_diff
        ):
            await _auto_emit_and_detect(
                handle=handle,
                tool_args=proposed_action or {},
            )


# ---------------------------------------------------------------------------
# Belief auto-extraction + live divergence detection (v0.2 week 5)
# ---------------------------------------------------------------------------
async def _auto_emit_and_detect(
    *, handle: "IntentionHandle", tool_args: dict,
) -> None:
    """Extract beliefs from the tool's state_diff using BYO-LLM, emit
    them, and run live divergence detection. Best-effort — any failure
    is logged + swallowed (the body already ran successfully)."""
    try:
        from synapse.beliefs.extractor import extract_beliefs_with_llm
        from synapse.beliefs.api import emit_belief

        # Pull the most-informative content from state_diff
        sd = handle.state_diff or {}
        output = sd.get("content") or sd.get("output") or sd.get("output_preview")
        if not output:
            # Fall back: serialize the whole state_diff
            output = str(sd)[:1500]

        facts = await extract_beliefs_with_llm(
            tool_name=tool_args.get("tool", "tool_call"),
            tool_args=tool_args,
            output=output,
        )
        for fact in facts:
            handle.beliefs_emitted.append({
                "key": fact.key,
                "value": fact.value,
                "confidence": fact.confidence,
                "evidence": fact.evidence,
            })
            div = await emit_belief(
                agent=handle.agent_id,
                session=handle.session_id,
                key=fact.key,
                value=fact.value,
                confidence=fact.confidence,
                source="observed",
                evidence=fact.evidence,
                detect_divergence=True,
            )
            if div is not None:
                handle.divergences.append(div.to_dict())
                logger.warning(
                    "synapse: BELIEF DIVERGENCE detected on key=%s "
                    "(%d distinct value(s) across %d agent(s)): %s",
                    div.key, len(div.distinct_values),
                    len(div.agents_involved), div.distinct_values,
                )
    except Exception as e:
        logger.warning("synapse: auto-extract beliefs failed (%s)", e)


# ---------------------------------------------------------------------------
# Cleanup helpers — used by tests and by ``synapse.install`` shutdown
# ---------------------------------------------------------------------------
def _jsonl_audit_path() -> Optional[str]:
    """Return the path that ``intend()`` should append intent records to,
    or None if not configured.

    Resolution order:
      1. ``SYNAPSE_AUDIT_LOG`` env var (explicit override).
      2. Auto-discovery: if a ``.synapse/runs/<session>.jsonl`` file
         exists in the cwd OR any parent directory (think git root),
         use it. This makes ``synapse watch`` work without the user
         having to export an env var in their second terminal — just
         run the agent script from the same project tree.

    The auto-discovery half is what the W1.4 audit (finding A4) flagged:
    the README's two-terminal flow was broken because the watch process
    set the env var but the agent's process couldn't see it.
    """
    explicit = os.environ.get("SYNAPSE_AUDIT_LOG")
    if explicit:
        return explicit
    session = os.environ.get("SYNAPSE_SESSION_ID") or "default"
    # Walk up from cwd looking for .synapse/runs/<session>.jsonl
    try:
        from pathlib import Path
        cur = Path.cwd().resolve()
        for parent in [cur, *cur.parents]:
            cand = parent / ".synapse" / "runs" / f"{session}.jsonl"
            if cand.exists():
                return str(cand)
            # Stop at git root or filesystem root
            if (parent / ".git").exists():
                break
    except Exception:
        pass
    return None


def _append_audit_jsonl(record: dict) -> None:
    """Best-effort JSONL append. Non-fatal: never lets I/O failure
    disrupt the user's tool dispatch."""
    path = _jsonl_audit_path()
    if not path:
        return
    try:
        import json as _json
        line = _json.dumps(record, default=str)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:  # pragma: no cover — defensive
        logger.debug("synapse: audit JSONL append failed (%s)", e)


async def shutdown() -> None:
    """Close bus + state graph connections, drop the agent cache.

    Safe to call multiple times; safe to call when nothing was set up.
    Also stops any in-process routers spawned for zero-infra mode so
    background tasks don't leak between test cases.
    """
    rt = _runtime
    routers = rt.get("_routers") or {}
    for sess, r in list(routers.items()):
        try:
            await r.stop()
        except Exception:
            pass
    if rt.get("connected"):
        bus = rt.get("bus")
        if bus is not None:
            try:
                await bus.close()
            except Exception:
                pass
        state = rt.get("state")
        if state is not None:
            try:
                await state.close()
            except Exception:
                pass
    _runtime.clear()
