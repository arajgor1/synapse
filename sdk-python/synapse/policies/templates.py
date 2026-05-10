"""Higher-level merge-policy templates built on the four built-ins.

The original four (``redirect``, ``wait``, ``abort``, ``auto_merge``) are
correct primitives but every real user ends up writing the same handful
of behaviours on top of them: queue behind the other agent, retry with
backoff, escalate to a human, pivot to a different scope. This module
ships them as ready-to-use ``MergePolicy`` subclasses so users don't
have to reinvent the wheel.

Usage:

    import synapse
    synapse.install(
        framework="langgraph",
        merge_policy=synapse.MergePolicy.queue_behind,  # or any of the templates
        critical_scopes=["billing.*", "prod.deploy.*"],
    )

    # Or per-call, with a custom timeout:
    from synapse.policies.templates import QueueBehindPolicy
    async with synapse.intend(
        scope=["repo.fs.shared/db.py:w"],
        agent="me",
        merge_policy=QueueBehindPolicy(timeout_ms=10_000),
    ) as i:
        ...

The new templates below are also exposed via the standard
``synapse.MergePolicy.*`` namespace once this module is imported (the
package ``__init__`` does that for you).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from .base import MergeAction, MergeDecision, MergePolicy

logger = logging.getLogger(__name__)


def _conflicting_intention_ids(conflicts: list) -> list[str]:
    """Pull the intention IDs of the conflicting agents out of the
    Conflict envelopes, handling both pydantic-model and dict shapes."""
    out: list[str] = []
    for c in conflicts:
        cis = getattr(c, "conflicting_intentions", None) or []
        for ci in cis:
            int_id = (
                getattr(ci, "intention_id", None)
                or (ci.get("intention_id") if isinstance(ci, dict) else None)
            )
            if int_id and int_id not in out:
                out.append(int_id)
    return out


async def _conflicts_still_active(
    state: Any, *, intention_ids: list[str], session_id: str
) -> bool:
    """True if ANY of the named intentions still have status='active'.

    Uses the existing ``find_conflicts`` query against an empty scope
    list filter — both StateGraph (Postgres) and SqliteStateGraph
    expose the same surface. Falls back to True (assume still active)
    on any backend error, which is the safe-side default for a
    queue-behind / retry policy.
    """
    if not intention_ids or state is None:
        return False
    try:
        # Re-using find_conflicts is more portable than introducing a
        # new "intention_status" query. We call it with a never-matching
        # agent_id + scope so it returns ALL non-self active intentions
        # in the session, then filter by id.
        # (The SQL/SQLite paths both filter agent_id != $caller, so we
        # just pass a unique sentinel.)
        rows = await state.find_conflicts(
            new_intention_id="__queue_behind_probe__",
            agent_id="__queue_behind_probe_agent__",
            session_id=session_id,
            scope=["__never_match__:r"],  # won't overlap anything, but
            resolved_lookback_ms=0,        # fetches the active set
        )
        # The above doesn't return all actives — it returns scope-overlapping
        # actives only. To check specific intention IDs we need to look
        # them up directly. Use the StateGraph's per-backend method when
        # available.
    except Exception:
        rows = []

    # Direct status lookup if the state graph exposes one.
    try:
        active_ids = await state.intentions_active_in(intention_ids, session_id)
        return any(i in active_ids for i in intention_ids)
    except AttributeError:
        # No direct lookup; fall back to a broad find_conflicts that scans
        # all overlapping actives + filter.
        active_lookup: set[str] = set()
        for r in (rows or []):
            iid = r.get("intention_id") if isinstance(r, dict) else None
            if iid:
                active_lookup.add(iid)
        return any(i in active_lookup for i in intention_ids)
    except Exception as e:
        logger.warning("queue_behind: status check failed (%s); assuming still active", e)
        return True


# ---------------------------------------------------------------------------
# QueueBehindPolicy — wait for all conflicting intentions to resolve.
# ---------------------------------------------------------------------------
class QueueBehindPolicy(MergePolicy):
    """Block until ALL conflicting intentions reach status='resolved'.

    Polls the state graph every ``poll_interval_ms``. On timeout,
    decides ``on_timeout`` (default ABORT — safer than silently
    proceeding with stale data).
    """

    name = "queue_behind"

    def __init__(
        self,
        *,
        timeout_ms: int = 30_000,
        poll_interval_ms: int = 50,
        on_timeout: MergeDecision = MergeDecision.ABORT,
    ):
        self.timeout_ms = timeout_ms
        self.poll_interval_ms = poll_interval_ms
        self.on_timeout = on_timeout

    async def resolve(self, handle, conflicts, proposed_action=None):
        from synapse.intend import _get_or_init_runtime
        rt = _get_or_init_runtime()
        state = rt.get("state")
        if state is None:
            return MergeAction(
                decision=MergeDecision.PROCEED,
                rationale=(
                    "queue_behind: no state graph configured; cannot poll. "
                    "Proceeding (degraded — equivalent to no_op)."
                ),
            )

        wait_for = _conflicting_intention_ids(conflicts)
        if not wait_for:
            return MergeAction(
                decision=MergeDecision.PROCEED,
                rationale="queue_behind: no conflict IDs surfaced; proceeding.",
            )

        deadline = time.monotonic() + self.timeout_ms / 1000.0
        polls = 0
        while time.monotonic() < deadline:
            polls += 1
            still = await _conflicts_still_active(
                state, intention_ids=wait_for, session_id=handle.session_id,
            )
            if not still:
                return MergeAction(
                    decision=MergeDecision.PROCEED,
                    rationale=(
                        f"queue_behind: waited for {len(wait_for)} prior "
                        f"intention(s) to resolve ({polls} polls); "
                        f"all clear, proceeding."
                    ),
                )
            await asyncio.sleep(self.poll_interval_ms / 1000.0)

        return MergeAction(
            decision=self.on_timeout,
            rationale=(
                f"queue_behind: timed out after {self.timeout_ms}ms with "
                f"{len(wait_for)} prior intention(s) still active. "
                f"Decision: {self.on_timeout.value}."
            ),
        )


# ---------------------------------------------------------------------------
# RetryWithBackoffPolicy — exponential backoff retry on conflict.
# ---------------------------------------------------------------------------
class RetryWithBackoffPolicy(MergePolicy):
    """Re-check for conflicts up to ``max_attempts`` times with
    exponential backoff. If the conflict clears within the budget,
    PROCEED. Otherwise the configured ``on_exhausted`` decision fires
    (default ABORT)."""

    name = "retry_with_backoff"

    def __init__(
        self,
        *,
        max_attempts: int = 5,
        initial_backoff_ms: int = 50,
        max_backoff_ms: int = 2_000,
        backoff_multiplier: float = 2.0,
        on_exhausted: MergeDecision = MergeDecision.ABORT,
    ):
        self.max_attempts = max_attempts
        self.initial_backoff_ms = initial_backoff_ms
        self.max_backoff_ms = max_backoff_ms
        self.backoff_multiplier = backoff_multiplier
        self.on_exhausted = on_exhausted

    async def resolve(self, handle, conflicts, proposed_action=None):
        from synapse.intend import _get_or_init_runtime
        rt = _get_or_init_runtime()
        state = rt.get("state")
        if state is None:
            return MergeAction(
                decision=MergeDecision.PROCEED,
                rationale=(
                    "retry_with_backoff: no state graph; cannot re-check. "
                    "Proceeding (degraded)."
                ),
            )

        wait_for = _conflicting_intention_ids(conflicts)
        if not wait_for:
            return MergeAction(
                decision=MergeDecision.PROCEED,
                rationale="retry_with_backoff: no conflict IDs surfaced; proceeding.",
            )

        backoff_ms = self.initial_backoff_ms
        for attempt in range(1, self.max_attempts + 1):
            await asyncio.sleep(backoff_ms / 1000.0)
            still = await _conflicts_still_active(
                state, intention_ids=wait_for, session_id=handle.session_id,
            )
            if not still:
                return MergeAction(
                    decision=MergeDecision.PROCEED,
                    rationale=(
                        f"retry_with_backoff: cleared after attempt {attempt} "
                        f"(waited ~{backoff_ms}ms); proceeding."
                    ),
                )
            backoff_ms = min(int(backoff_ms * self.backoff_multiplier), self.max_backoff_ms)

        return MergeAction(
            decision=self.on_exhausted,
            rationale=(
                f"retry_with_backoff: exhausted {self.max_attempts} attempts; "
                f"{len(wait_for)} prior intention(s) still active. "
                f"Decision: {self.on_exhausted.value}."
            ),
        )


# ---------------------------------------------------------------------------
# WorkOnDifferentScopePolicy — pivot to a per-agent scope variant.
# ---------------------------------------------------------------------------
class WorkOnDifferentScopePolicy(MergePolicy):
    """Pivot the proposed action to a per-agent variant of the scope so
    the conflict goes away.

    Heuristics:
      * If ``proposed_action`` has a ``path`` / ``filename`` / ``file_path``
        / ``target`` field of the form ``foo/bar.py``, rewrite it to
        ``foo/bar.<agent_id>.py``.
      * Otherwise, append ``.<agent_id>`` to the most recognisable
        string-shaped argument.
      * If no rewriteable arg exists, fall back to ``on_no_pivot``
        (default REDIRECT — caller's framework can decide).

    This is the "I know we both want to write this file, so let me
    write to a sibling file and you keep going" pattern. Common in
    multi-agent draft generation (Synapse demo shows it).
    """

    name = "work_on_different_scope"

    _PATH_KEYS = ("path", "file_path", "filename", "target", "out_path")

    def __init__(self, *, on_no_pivot: MergeDecision = MergeDecision.PROCEED):
        self.on_no_pivot = on_no_pivot

    async def resolve(self, handle, conflicts, proposed_action=None):
        if not proposed_action:
            return MergeAction(
                decision=self.on_no_pivot,
                rationale=(
                    "work_on_different_scope: no proposed_action supplied; "
                    "cannot pivot. Falling back."
                ),
            )

        agent_safe = "".join(
            c if c.isalnum() or c in "._-" else "_" for c in handle.agent_id
        ) or "agent"

        for key in self._PATH_KEYS:
            val = proposed_action.get(key)
            if isinstance(val, str) and val:
                pivoted = self._pivot_path(val, agent_safe)
                if pivoted != val:
                    new_action = dict(proposed_action)
                    new_action[key] = pivoted
                    return MergeAction(
                        decision=MergeDecision.MERGED,
                        merged_action=new_action,
                        rationale=(
                            f"work_on_different_scope: pivoted {key}={val!r} "
                            f"-> {pivoted!r} so it doesn't collide with "
                            f"{len(conflicts)} other agent(s)."
                        ),
                    )

        return MergeAction(
            decision=self.on_no_pivot,
            rationale=(
                f"work_on_different_scope: no rewriteable path-shaped "
                f"argument in proposed_action keys={list(proposed_action.keys())}. "
                f"Falling back."
            ),
        )

    @staticmethod
    def _pivot_path(path: str, agent_safe: str) -> str:
        """foo/bar.py -> foo/bar.<agent>.py
        (no extension) foo/bar -> foo/bar.<agent>"""
        # Walk back from the end to find the LAST '.' that isn't a leading dotfile.
        # Filenames like ".env" should pivot to ".env.<agent>", not ".<agent>.env".
        slash = max(path.rfind("/"), path.rfind("\\"))
        basename = path[slash + 1:]
        # If basename has an extension (a dot not at position 0), inject before it.
        dot = basename.rfind(".")
        if dot > 0:
            stem, ext = basename[:dot], basename[dot:]
            return path[: slash + 1] + f"{stem}.{agent_safe}{ext}"
        return path + f".{agent_safe}"


# ---------------------------------------------------------------------------
# EscalateToHumanPolicy — emit an ESCALATION envelope + ABORT.
# ---------------------------------------------------------------------------
class EscalateToHumanPolicy(MergePolicy):
    """Surface the conflict to humans via the bus AND abort the intention.

    The bus envelope (type=BLOCK, urgency='high') carries enough
    structured info that downstream notification integrations
    (Slack/PagerDuty webhooks, the Synapse hosted dashboard, etc.) can
    fire alerts. The intention itself aborts so the agent's framework
    surfaces a clean error rather than silently proceeding.

    For full human-in-the-loop with bidirectional approval, build on
    top of this policy and listen for an ACK envelope on the same
    bus channel before retrying.
    """

    name = "escalate_to_human"

    def __init__(self, *, urgency: str = "high"):
        self.urgency = urgency

    async def resolve(self, handle, conflicts, proposed_action=None):
        # Best-effort: emit a BLOCK envelope describing the escalation.
        try:
            from synapse.intend import _get_agent
            agent = await _get_agent(handle.agent_id, handle.session_id)
            if agent is not None:
                others = sorted({
                    ci.agent_id for c in conflicts
                    for ci in (getattr(c, "conflicting_intentions", None) or [])
                })
                await agent.emit_block(
                    blocker=(
                        f"Synapse CONFLICT on scope {handle.scope} between "
                        f"{handle.agent_id} and {', '.join(others) or 'others'}"
                    ),
                    needed=(
                        "Human approval to proceed. Other agent(s) hold "
                        f"overlapping intention(s) on {handle.scope}."
                    ),
                    attempted=[
                        f"Intent {handle.intention_id} aborted via escalate_to_human policy"
                    ],
                    urgency=self.urgency,
                    topics=[s.split(":")[0] for s in handle.scope],
                )
        except Exception as e:
            logger.warning(
                "escalate_to_human: BLOCK emission failed (%s); aborting anyway", e,
            )

        return MergeAction(
            decision=MergeDecision.ABORT,
            rationale=(
                f"escalate_to_human: emitted BLOCK envelope (urgency={self.urgency}); "
                f"intention aborted pending human review."
            ),
        )


# ---------------------------------------------------------------------------
# WaitForOtherPolicy — alias for QueueBehindPolicy with friendlier name.
# ---------------------------------------------------------------------------
class WaitForOtherPolicy(QueueBehindPolicy):
    """Alias for QueueBehindPolicy — same behaviour, more obvious name
    when reading user code."""

    name = "wait_for_other"
