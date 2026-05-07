"""Module-level LLM config — set once, read everywhere."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from synapse.adapters.base import InferenceAdapter

logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    """The two-LLM split: a primary model for user-facing decisions
    (auto-merge, escalation messages) and a cheaper internal model for
    high-frequency reasoning (scope inference, belief divergence).

    If only ``primary`` is set, ``internal`` falls back to it.
    """
    primary: Optional[InferenceAdapter] = None
    internal: Optional[InferenceAdapter] = None

    def get_internal(self) -> Optional[InferenceAdapter]:
        return self.internal or self.primary

    def get_primary(self) -> Optional[InferenceAdapter]:
        return self.primary


_config: LLMConfig = LLMConfig()
_logged_unset_warning = False


def set_llm(
    primary: InferenceAdapter,
    internal: Optional[InferenceAdapter] = None,
) -> None:
    """Configure the LLM(s) Synapse will use for internal reasoning.

    Args:
        primary: Adapter used for user-facing decisions (auto-merge, etc.).
            Required.
        internal: Cheaper adapter for high-frequency calls (scope inference
            fallback, belief divergence). Optional — defaults to ``primary``.
    """
    if not isinstance(primary, InferenceAdapter):
        raise TypeError(
            f"synapse.set_llm() expects an InferenceAdapter, got "
            f"{type(primary).__name__}. Use synapse.from_anthropic() / "
            f"synapse.from_openai() / synapse.from_litellm() / "
            f"synapse.from_langchain() to wrap a vendor client."
        )
    if internal is not None and not isinstance(internal, InferenceAdapter):
        raise TypeError(
            f"synapse.set_llm() internal= expects an InferenceAdapter, got "
            f"{type(internal).__name__}."
        )
    _config.primary = primary
    _config.internal = internal
    logger.info(
        "synapse.set_llm: primary=%s internal=%s",
        getattr(primary.capabilities, "backend_id", type(primary).__name__),
        getattr(internal, "capabilities", None)
        and getattr(internal.capabilities, "backend_id", type(internal).__name__),
    )


def get_llm() -> Optional[InferenceAdapter]:
    """Return the primary adapter, or None if unconfigured."""
    global _logged_unset_warning
    if _config.primary is None and not _logged_unset_warning:
        logger.info(
            "synapse: no LLM configured (synapse.set_llm() was not called). "
            "L1 + L2 routing still work; LLM-mediated features (scope inference "
            "fallback, belief divergence, auto-merge, L3 semantic routing) "
            "are no-ops in this run."
        )
        _logged_unset_warning = True
    return _config.primary


def get_internal_llm() -> Optional[InferenceAdapter]:
    """Return the internal adapter (cheap variant), or fall back to primary."""
    return _config.get_internal() or get_llm()


def is_configured() -> bool:
    return _config.primary is not None


def clear() -> None:
    """Reset the LLM config (mostly for tests)."""
    global _logged_unset_warning
    _config.primary = None
    _config.internal = None
    _logged_unset_warning = False
