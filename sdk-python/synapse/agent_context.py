"""Per-task agent attribution via contextvars.

The pre-v0.2.3 attribution scheme used `os.environ["SYNAPSE_AGENT_ID"]`
which races under asyncio.gather (last writer wins, both attributions
collapse to the same name). This module replaces that with a
contextvars.ContextVar that's per-task by construction.

Resolution order for `current_agent_id()`:
  1. ContextVar (set by `set_agent_context(name)` or `with_agent(...)`)
  2. SYNAPSE_AGENT_ID env var (legacy, still honored)
  3. SYNAPSE_DEFAULT_AGENT_ID env var
  4. The framework adapter's hardcoded fallback (e.g. "smolagents_agent")

Public API:
    synapse.set_agent_context("alice")      # set for current task
    synapse.with_agent("alice")             # context-manager form
    synapse.current_agent_id(default="x")   # read

ContextVars naturally propagate through asyncio.gather, asyncio.create_task,
asyncio.to_thread, and concurrent.futures via copy_context().
"""
from __future__ import annotations

import contextvars
import os
from contextlib import contextmanager
from typing import Iterator, Optional


# Module-level ContextVar — None when unset (then falls back to env vars).
_AGENT_CTX: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "synapse_agent_id", default=None
)


def set_agent_context(agent_id: str) -> contextvars.Token:
    """Set the agent identity for THIS task and any tasks it spawns.

    Returns a Token you can pass to `reset_agent_context(token)` to
    restore the previous value. Most users prefer the `with_agent(...)`
    context manager.
    """
    return _AGENT_CTX.set(agent_id)


def reset_agent_context(token: contextvars.Token) -> None:
    """Restore the agent context to its previous value."""
    _AGENT_CTX.reset(token)


@contextmanager
def with_agent(agent_id: str) -> Iterator[None]:
    """Context manager: set agent_id for the with-block, restore on exit.

    Example:

        async with synapse.with_agent("alice"):
            await my_tool.run(...)

    Or in a sync block:

        with synapse.with_agent("alice"):
            my_tool(...)
    """
    token = _AGENT_CTX.set(agent_id)
    try:
        yield
    finally:
        _AGENT_CTX.reset(token)


def current_agent_id(default: Optional[str] = None) -> str:
    """Resolve the current agent_id for this task.

    Resolution order (each falls through if None / empty):
      1. ContextVar set via set_agent_context() / with_agent()
      2. SYNAPSE_AGENT_ID env var
      3. SYNAPSE_DEFAULT_AGENT_ID env var
      4. The `default` argument
      5. "synapse_agent" as a last resort
    """
    ctx_val = _AGENT_CTX.get()
    if ctx_val:
        return ctx_val
    env_val = os.environ.get("SYNAPSE_AGENT_ID")
    if env_val:
        return env_val
    default_env = os.environ.get("SYNAPSE_DEFAULT_AGENT_ID")
    if default_env:
        return default_env
    return default or "synapse_agent"
