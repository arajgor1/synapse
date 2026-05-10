"""Merge policies — what to do when ``synapse.intend()`` detects a CONFLICT.

v0.1 / v0.2-week2 detected conflicts but always proceeded with a warning.
This module ships explicit, opt-in policies for what should happen instead:

  - ``redirect``   (default) — re-prompt the agent's LLM with the other
                   agent's recent work so it can revise its action
  - ``wait``       — block until the other agent's RESOLUTION lands
                   (with a timeout)
  - ``abort``      — fail the intention with a clean SynapseConflict
                   so the caller's framework retries / escalates
  - ``auto_merge`` — opt-in: ask the user's LLM (via ``synapse.set_llm``)
                   to merge the two writes and return a unified version

Plus a ``critical_scopes`` mechanism: a list of glob patterns that, when
matched, force ``abort`` regardless of the configured policy. Use this
for production-sensitive scopes (billing, deploy, schema migrations).

Usage:

    import synapse
    synapse.install(
        framework="langgraph",
        merge_policy=synapse.MergePolicy.redirect,
        critical_scopes=["billing.*", "prod.deploy.*"],
    )

    # Or per-call:
    async with synapse.intend(
        scope=["repo.fs.user.py:w"],
        agent="api_engineer",
        merge_policy=synapse.MergePolicy.auto_merge,
        proposed_action={"path": "user.py", "content": "..."},
    ) as i:
        if i.merged_action:
            # auto_merge filled this in — use it instead of your original args
            await write_file(**i.merged_action)
        else:
            await write_file(path=..., content=...)
"""
from __future__ import annotations

from .base import MergePolicy, MergeAction, MergeDecision, SynapseConflict
from .builtin import (
    RedirectPolicy,
    WaitPolicy,
    AbortPolicy,
    AutoMergePolicy,
    NoOpPolicy,
)
from .templates import (
    QueueBehindPolicy,
    WaitForOtherPolicy,
    WorkOnDifferentScopePolicy,
    EscalateToHumanPolicy,
    RetryWithBackoffPolicy,
)
from .registry import resolve_policy, PolicyLike  # noqa: F401 (also wires .redirect etc. onto MergePolicy)
from .critical import critical_scope_match, normalize_critical_scopes

__all__ = [
    "MergePolicy",
    "MergeAction",
    "MergeDecision",
    "SynapseConflict",
    "RedirectPolicy",
    "WaitPolicy",
    "AbortPolicy",
    "AutoMergePolicy",
    "NoOpPolicy",
    # v0.2.2a4 policy templates
    "QueueBehindPolicy",
    "WaitForOtherPolicy",
    "WorkOnDifferentScopePolicy",
    "EscalateToHumanPolicy",
    "RetryWithBackoffPolicy",
    "critical_scope_match",
    "normalize_critical_scopes",
]
