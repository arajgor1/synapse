"""Four built-in MergePolicies covering the common cases."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from .base import MergeAction, MergeDecision, MergePolicy, SynapseConflict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# NoOp — proceed with a warning. Equivalent to v0.1 behavior.
# ---------------------------------------------------------------------------
class NoOpPolicy(MergePolicy):
    """Proceed silently after logging the conflict."""

    name = "no_op"

    async def resolve(self, handle, conflicts, proposed_action=None):
        return MergeAction(
            decision=MergeDecision.PROCEED,
            rationale=f"Proceeding through {len(conflicts)} conflict(s) (no_op policy).",
        )


# ---------------------------------------------------------------------------
# Abort — fail the intention with a SynapseConflict.
# ---------------------------------------------------------------------------
class AbortPolicy(MergePolicy):
    """Fail the intention. The caller's framework receives a clean
    ``SynapseConflict`` exception it can handle natively."""

    name = "abort"

    async def resolve(self, handle, conflicts, proposed_action=None):
        return MergeAction(
            decision=MergeDecision.ABORT,
            rationale=(
                f"Aborted: {len(conflicts)} other agent(s) hold conflicting "
                f"intentions on {handle.scope}. Caller should pivot."
            ),
        )


# ---------------------------------------------------------------------------
# Wait — block until prior conflicts resolve, then proceed.
# ---------------------------------------------------------------------------
class WaitPolicy(MergePolicy):
    """Block briefly then proceed. The intend() runtime polls the state
    graph for the conflicting intentions to flip to status='resolved'.
    """

    name = "wait"

    def __init__(self, timeout_ms: int = 5000):
        self.timeout_ms = timeout_ms

    async def resolve(self, handle, conflicts, proposed_action=None):
        return MergeAction(
            decision=MergeDecision.WAIT,
            wait_timeout_ms=self.timeout_ms,
            rationale=f"Waiting up to {self.timeout_ms}ms for {len(conflicts)} prior intention(s) to resolve.",
        )


# ---------------------------------------------------------------------------
# Redirect — re-emit with the other agent's recent work as context.
# ---------------------------------------------------------------------------
class RedirectPolicy(MergePolicy):
    """Default policy: surface the conflict to the caller as a structured
    rationale so the caller's framework / agent can re-prompt the LLM
    with the other agent's recent work in context.

    This policy doesn't itself call an LLM. It just packages the
    conflict information cleanly. It's the safest default for
    production: alerts loud, never silently merges, never blocks.
    """

    name = "redirect"

    async def resolve(self, handle, conflicts, proposed_action=None):
        others = sorted({
            ci.agent_id for c in conflicts
            for ci in (getattr(c, "conflicting_intentions", None) or [])
        }) or ["other agent(s)"]

        suggested = ", ".join(
            getattr(c, "suggested_resolution", "pivot") or "pivot" for c in conflicts
        )
        rationale = (
            f"Other agent(s) ({', '.join(others)}) hold overlapping "
            f"intention(s) on scope {handle.scope}. Suggested action: "
            f"{suggested}. Caller should pivot — re-prompt the LLM with "
            f"the other agent(s)' recent work in context, then re-invoke."
        )
        return MergeAction(
            decision=MergeDecision.PROCEED,
            rationale=rationale,
        )


# ---------------------------------------------------------------------------
# Auto-merge — opt-in: ask the user's BYO-LLM to merge two writes.
# ---------------------------------------------------------------------------
class AutoMergePolicy(MergePolicy):
    """Opt-in: ask the user's configured LLM (via ``synapse.set_llm``)
    to merge the conflicting writes and return a unified version.

    Requires:
      1. ``synapse.set_llm()`` has been called (or auto-detect succeeds)
      2. ``proposed_action`` contains the agent's planned content (e.g.
         ``{"path": "user.py", "content": "..."}``)
      3. The conflicting RESOLUTION's ``state_diff`` carries the other
         agent's content under a known key (``content``, ``output``, or
         ``output_preview``).

    On success, returns ``MergeAction(decision=MERGED, merged_action=...)``
    with merged content under the same key the caller used. On failure
    (no LLM configured, missing content, LLM error), falls back to
    REDIRECT semantics — never silently writes the wrong thing.
    """

    name = "auto_merge"

    def __init__(self, *, content_key: str = "content"):
        self.content_key = content_key

    async def resolve(self, handle, conflicts, proposed_action=None):
        from synapse.llm.config import get_internal_llm
        from synapse.policies.base import MergeAction, MergeDecision

        llm = get_internal_llm()
        if llm is None:
            logger.info(
                "auto_merge: no LLM configured (synapse.set_llm() unset). "
                "Falling back to redirect."
            )
            return MergeAction(
                decision=MergeDecision.PROCEED,
                rationale="auto_merge skipped (no LLM); use synapse.set_llm() to enable.",
            )

        if not proposed_action or self.content_key not in proposed_action:
            return MergeAction(
                decision=MergeDecision.PROCEED,
                rationale=(
                    f"auto_merge requires proposed_action[{self.content_key!r}] — "
                    f"caller didn't supply it. Falling back to redirect."
                ),
            )

        # Find ALL conflicting agents' recent content (not just the first).
        # Multi-agent collisions need a multi-way merge.
        priors = await _fetch_all_prior_content(handle, conflicts, self.content_key)
        if not priors:
            return MergeAction(
                decision=MergeDecision.PROCEED,
                rationale=(
                    "auto_merge: couldn't fetch prior agent's content "
                    "(state graph unavailable or no state_diff). Redirecting."
                ),
            )

        my_content = proposed_action[self.content_key]
        merged = await _llm_merge_multi(
            llm,
            priors=priors,
            my_agent=handle.agent_id,
            my_content=my_content,
            scope=handle.scope,
        )

        if not merged:
            return MergeAction(
                decision=MergeDecision.PROCEED,
                rationale="auto_merge: LLM returned empty merge. Falling back to redirect.",
            )

        merged_action = dict(proposed_action)
        merged_action[self.content_key] = merged
        prior_names = ", ".join(p["agent_id"] for p in priors)
        return MergeAction(
            decision=MergeDecision.MERGED,
            merged_action=merged_action,
            rationale=(
                f"Auto-merged {handle.agent_id}'s draft with {len(priors)} prior "
                f"agent(s) ({prior_names}) via LLM."
            ),
        )


async def _fetch_all_prior_content(
    handle, conflicts, content_key: str
) -> list[dict]:
    """Pull EVERY conflicting agent's recent content. Returns a list
    (possibly empty); each item has ``agent_id``, ``intention_id``, ``content``.
    """
    from synapse.intend import _get_or_init_runtime

    rt = _get_or_init_runtime()
    bus = rt.get("bus")
    if bus is None:
        return []

    handle_session_id = getattr(handle, "session_id", None)
    out: list[dict] = []
    seen_intents: set[str] = set()

    for c in conflicts:
        cis = getattr(c, "conflicting_intentions", None) or []
        for ci in cis:
            int_id = getattr(ci, "intention_id", None) or (ci.get("intention_id") if isinstance(ci, dict) else None)
            agent_id = getattr(ci, "agent_id", None) or (ci.get("agent_id") if isinstance(ci, dict) else "unknown")
            if not int_id or int_id in seen_intents:
                continue
            seen_intents.add(int_id)
            content = await _read_resolution_state_diff(rt, int_id, content_key, session_id=handle_session_id)
            logger.info(
                "auto_merge: prior intention=%s agent=%s -> content_len=%d",
                int_id, agent_id, len(content) if content else 0,
            )
            if content:
                out.append({"agent_id": str(agent_id), "intention_id": int_id, "content": content})
    return out


async def _fetch_prior_content(
    handle, conflicts, content_key: str
) -> Optional[dict]:
    """Pull the conflicting agent's RESOLUTION state_diff from the state
    graph (which holds the most recent finished writes).
    """
    from synapse.intend import _get_or_init_runtime

    rt = _get_or_init_runtime()
    bus = rt.get("bus")
    if bus is None:
        logger.info("auto_merge: rt has no bus (mode=%s)", rt.get("mode"))
        return None

    n_conflicts = len(conflicts)
    n_cis = sum(len(getattr(c, "conflicting_intentions", None) or []) for c in conflicts)
    logger.info("auto_merge: scanning %d conflict(s) with %d conflicting_intention(s)", n_conflicts, n_cis)

    # Use the IntentionHandle's session_id directly — stale cache entries
    # from earlier sessions can mislead the runtime peek.
    handle_session_id = getattr(handle, "session_id", None)

    # The conflicts come from the L2 router's CONFLICT envelope
    for c in conflicts:
        cis = getattr(c, "conflicting_intentions", None) or []
        for ci in cis:
            int_id = getattr(ci, "intention_id", None) or (ci.get("intention_id") if isinstance(ci, dict) else None)
            agent_id = getattr(ci, "agent_id", None) or (ci.get("agent_id") if isinstance(ci, dict) else "unknown")
            if not int_id:
                continue
            content = await _read_resolution_state_diff(rt, int_id, content_key, session_id=handle_session_id)
            logger.info("auto_merge: prior intention=%s agent=%s -> content_len=%d",
                        int_id, agent_id, len(content) if content else 0)
            if content:
                return {"agent_id": str(agent_id), "intention_id": int_id, "content": content}
    return None


async def _read_resolution_state_diff(
    rt: dict, intention_id: str, content_key: str, session_id: Optional[str] = None,
) -> Optional[str]:
    """Look up the RESOLUTION for ``intention_id`` on the session stream,
    return its state_diff[content_key] if present.
    """
    bus = rt.get("bus")
    sid = session_id or _peek_session_from_runtime(rt)
    if bus is None or sid is None:
        logger.info("auto_merge.lookup: bus=%s session_id=%s", bool(bus), sid)
        return None
    stream = f"synapse:session:{sid}:events"
    try:
        entries = await bus.redis.xrange(stream, count=500)
    except Exception as e:
        logger.warning("auto_merge.lookup: xrange failed: %s", e)
        return None
    n_entries = len(entries)
    n_resolutions = 0
    for _eid, fields in entries:
        try:
            env = json.loads(fields["e"])
        except Exception:
            continue
        if env.get("type") != "RESOLUTION":
            continue
        n_resolutions += 1
        payload = env.get("payload") or {}
        if payload.get("intention_id") != intention_id:
            continue
        sd = payload.get("state_diff") or {}
        logger.info("auto_merge.lookup: matched RESOLUTION for intent=%s; state_diff keys=%s",
                    intention_id, list(sd.keys()))
        for k in (content_key, "content", "output_preview", "output"):
            if k in sd and sd[k]:
                return str(sd[k])
    logger.info("auto_merge.lookup: scanned %d entries (%d RESOLUTIONs), no match for intent=%s",
                n_entries, n_resolutions, intention_id)
    return None


def _peek_session_from_runtime(rt: dict) -> Optional[str]:
    """Best-effort session lookup. ``intend()`` doesn't store the session
    on the runtime dict (each call passes its own), so we peek at the
    cached agents and use the first one's session.
    """
    agents = rt.get("agents") or {}
    for key in agents:
        # Cache key is f"{session_id}::{agent_id}"
        if "::" in key:
            return key.split("::", 1)[0]
    import os
    return os.environ.get("SYNAPSE_SESSION_ID")


async def _llm_merge_multi(
    llm,
    *,
    priors: list[dict],
    my_agent: str,
    my_content: str,
    scope: list[str],
) -> str:
    """Multi-way merge: combine my_content with N prior agents' content."""
    prior_blocks = "\n\n".join(
        f"Agent {p['agent_id']} wrote:\n```\n{p['content']}\n```"
        for p in priors
    )
    prompt = (
        f"Multiple AI agents wrote conflicting content for the same scope ({', '.join(scope)}).\n\n"
        f"PRIOR AGENT WRITES (in order, oldest first):\n\n"
        f"{prior_blocks}\n\n"
        f"NEW AGENT ({my_agent}) is about to write:\n```\n{my_content}\n```\n\n"
        f"Produce a single merged version that incorporates EVERY agent's intent.\n"
        f"  - Preserve fields/decisions from ALL agents — do not drop any contribution.\n"
        f"  - If two agents conflict semantically (e.g. different formulas), pick the\n"
        f"    one that looks more correct and add an inline comment.\n"
        f"  - Output only the merged content, no explanation, no markdown fences."
    )
    return await _llm_call_text(llm, prompt)


async def _llm_call_text(llm, prompt: str) -> str:
    """Generic LLM call helper supporting bridge + native adapters."""
    messages = [{"role": "user", "content": prompt}]

    # Path 1: bridge adapters
    try:
        if hasattr(llm, "generate"):
            text = await llm.generate(messages=messages, max_tokens=1500, temperature=0.0)
            if isinstance(text, str) and text.strip():
                return text.strip()
    except Exception as e:
        logger.warning("auto_merge: llm.generate failed (%s)", e)

    # Path 2: native Anthropic adapter
    client = getattr(llm, "_client", None)
    model = getattr(llm, "_model", None) or "claude-haiku-4-5-20251001"
    if client is not None and hasattr(client, "messages"):
        try:
            msg = await client.messages.create(
                model=model, max_tokens=1500, messages=messages,
            )
            blocks = msg.content if msg and getattr(msg, "content", None) else []
            text = blocks[0].text if blocks and hasattr(blocks[0], "text") else ""
            if text and text.strip():
                return text.strip()
        except Exception as e:
            logger.warning("auto_merge: anthropic client fallback failed (%s)", e)

    # Path 3: native OpenAI adapter
    if client is not None and hasattr(client, "chat") and hasattr(client.chat, "completions"):
        try:
            resp = await client.chat.completions.create(
                model=model, max_tokens=1500, messages=messages, temperature=0.0,
            )
            text = resp.choices[0].message.content if resp.choices else ""
            if text and text.strip():
                return text.strip()
        except Exception as e:
            logger.warning("auto_merge: openai client fallback failed (%s)", e)

    return ""


async def _llm_merge(
    llm,
    *,
    prior_agent: str,
    prior_content: str,
    my_agent: str,
    my_content: str,
    scope: list[str],
) -> str:
    """Call the user's LLM to produce a merged version.

    Tries ``llm.generate(messages=...)`` first (the bridge / cheap-variant
    path), then falls back to whatever the adapter exposes.
    """
    prompt = (
        f"Two AI agents both wrote content for the same scope ({', '.join(scope)}).\n\n"
        f"Agent A ({prior_agent}) wrote (just now, BEFORE you saw it):\n"
        f"```\n{prior_content}\n```\n\n"
        f"Agent B ({my_agent}) is about to write:\n"
        f"```\n{my_content}\n```\n\n"
        f"Produce a single merged version that incorporates both agents' "
        f"intent. Preserve fields/decisions from BOTH agents — do not drop "
        f"either's contribution. If they conflict semantically (e.g. "
        f"different formulas for the same field), prefer the one that "
        f"looks more correct and add an inline comment noting the choice.\n\n"
        f"Output ONLY the merged content, no explanation, no markdown fences."
    )
    messages = [{"role": "user", "content": prompt}]

    # Path 1: bridge adapters (LangChain / LiteLLM) — they expose .generate()
    try:
        if hasattr(llm, "generate"):
            text = await llm.generate(messages=messages, max_tokens=1500, temperature=0.0)
            if isinstance(text, str) and text.strip():
                return text.strip()
    except Exception as e:
        logger.warning("auto_merge: llm.generate failed (%s)", e)

    # Path 2: native Anthropic adapter — poke at the underlying client
    client = getattr(llm, "_client", None)
    model = getattr(llm, "_model", None) or "claude-haiku-4-5-20251001"
    if client is not None and hasattr(client, "messages"):
        try:
            msg = await client.messages.create(
                model=model,
                max_tokens=1500,
                messages=messages,
            )
            blocks = msg.content if msg and getattr(msg, "content", None) else []
            text = blocks[0].text if blocks and hasattr(blocks[0], "text") else ""
            if text and text.strip():
                return text.strip()
        except Exception as e:
            logger.warning("auto_merge: anthropic client fallback failed (%s)", e)

    # Path 3: native OpenAI adapter — chat.completions
    if client is not None and hasattr(client, "chat") and hasattr(client.chat, "completions"):
        try:
            resp = await client.chat.completions.create(
                model=model,
                max_tokens=1500,
                messages=messages,
                temperature=0.0,
            )
            text = resp.choices[0].message.content if resp.choices else ""
            if text and text.strip():
                return text.strip()
        except Exception as e:
            logger.warning("auto_merge: openai client fallback failed (%s)", e)

    return ""
