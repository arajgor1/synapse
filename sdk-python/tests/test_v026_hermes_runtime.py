"""Regression tests for v0.2.6 hermes runtime isolation fix.

Phase 5 root-caused [3, 1, 1] hermes flakiness as stale ``_hermes_runtime``
state carrying over between reps in the same Python process. v0.2.6
exposes two public hooks:

  1. ``synapse.integrations.hermes_integration.clear_runtime()`` —
     clears the module-level dict
  2. ``install_hermes_synapse_hooks(force_reset=True)`` — same thing
     inlined into the install call

Both must work; both must leave the runtime in a clean state.
"""
from __future__ import annotations

import pytest


def test_clear_runtime_resets_module_dict():
    """clear_runtime() must drop all keys from _hermes_runtime."""
    from synapse.integrations.hermes_integration import (
        _hermes_runtime, clear_runtime,
    )

    # Seed some data
    _hermes_runtime["bus"] = object()
    _hermes_runtime["session_id"] = "old_session"
    _hermes_runtime["agents"] = {"old_agent": object()}

    clear_runtime()

    assert _hermes_runtime == {}, f"runtime not cleared: {_hermes_runtime}"


def test_install_hooks_force_reset_param_exists():
    """install_hermes_synapse_hooks must accept force_reset=True kwarg
    (v0.2.6 addition)."""
    import inspect
    from synapse.integrations.hermes_integration import install_hermes_synapse_hooks
    sig = inspect.signature(install_hermes_synapse_hooks)
    assert "force_reset" in sig.parameters, (
        f"force_reset param missing: {list(sig.parameters)}"
    )
    # Default must be False (preserves backward compat)
    assert sig.parameters["force_reset"].default is False
