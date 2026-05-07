"""Base types for merge policies."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from synapse.messages import Conflict
    from synapse.intend import IntentionHandle


class MergeDecision(str, Enum):
    """What the policy decided when it saw a CONFLICT."""

    PROCEED = "proceed"      # caller's original action stands; just log
    ABORT = "abort"          # fail the intention with SynapseConflict
    WAIT = "wait"            # block then retry (handled by intend)
    MERGED = "merged"        # auto_merge produced .merged_action


@dataclass
class MergeAction:
    """The policy's decision, returned to ``synapse.intend()``."""

    decision: MergeDecision
    # Only set when decision == MERGED — the new tool args / content the
    # caller should use instead of their original ``proposed_action``.
    merged_action: Optional[dict[str, Any]] = None
    # Free-form rationale (logged + surfaced to the agent's LLM if redirect)
    rationale: str = ""
    # Used when decision == WAIT
    wait_timeout_ms: int = 5000


class SynapseConflict(RuntimeError):
    """Raised by a policy that decides ABORT.

    Carries the conflicts for the caller's framework to inspect. Most
    framework adapters surface this as the framework's native error type
    (LangGraph node error, CrewAI task failure, etc.).
    """

    def __init__(
        self,
        conflicts: list,
        scopes: list[str],
        rationale: str = "",
    ) -> None:
        self.conflicts = conflicts
        self.scopes = scopes
        self.rationale = rationale
        super().__init__(
            rationale or f"Synapse CONFLICT on scope(s) {scopes}: "
            f"{len(conflicts)} other agent(s) hold overlapping intentions"
        )


class MergePolicy(ABC):
    """A pluggable strategy for handling CONFLICTs at intend() time.

    Subclass and implement ``resolve()`` to add custom behavior. The four
    built-ins (RedirectPolicy / WaitPolicy / AbortPolicy / AutoMergePolicy)
    cover the common cases.
    """

    name: str = "base"

    @abstractmethod
    async def resolve(
        self,
        handle: "IntentionHandle",
        conflicts: list,  # list[Conflict]
        proposed_action: Optional[dict[str, Any]] = None,
    ) -> MergeAction:
        """Decide what to do given a conflict + the caller's planned action.

        Args:
            handle: the IntentionHandle from ``synapse.intend()``.
                Has scope, agent_id, session_id, intention_id.
            conflicts: list of Conflict envelope payloads.
            proposed_action: what the agent is about to do (tool args /
                content). Required for ``auto_merge``; optional for others.

        Returns:
            MergeAction with the decision + optional merged_action.
        """
        raise NotImplementedError
