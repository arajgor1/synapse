"""Adapter health gate — regression check against API drift in real published SDKs.

This test is the institutional memory of the May-2026 incident where
the Strands and Pydantic AI adapters silently no-op'd against their
real published packages because the smoke tests used hand-built fakes.

For each framework adapter, we check:
  1. Whether the underlying SDK is installed in this environment
  2. If installed, whether `synapse.install(framework=X)` logs `"patched"`
     (meaning the wrapper was attached) without `"could not find"`

If the SDK is not installed, the test is skipped (we don't fail on a
missing optional dep). If installed, the adapter MUST patch — or the
test fails loudly so the next release doesn't ship a broken adapter.

To extend coverage, add real-SDK integration tests in CI that pip-install
each adapter's target package on a matrix.
"""
from __future__ import annotations

import importlib
import logging
import sys
from typing import Optional

import pytest


# (synapse framework name, pip package import name, is module path importable?)
ADAPTERS = [
    ("autogen", "autogen_agentchat"),
    ("crewai", "crewai"),
    ("hermes", "hermes"),
    ("langgraph", "langgraph"),
    ("openai_agents", "agents"),
    ("pydantic_ai", "pydantic_ai"),
    ("smolagents", "smolagents"),
    ("strands", "strands"),
]


def _capture_install_logs(framework_name: str) -> list[str]:
    """Run synapse.install(framework=X) and capture INFO/WARNING from
    `synapse.frameworks.*` loggers."""
    captured: list[str] = []

    class _H(logging.Handler):
        def emit(self, record):
            try:
                captured.append(self.format(record))
            except Exception:
                captured.append(record.getMessage())

    handler = _H()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    syn_logger = logging.getLogger("synapse")
    syn_logger.addHandler(handler)
    prev_level = syn_logger.level
    syn_logger.setLevel(logging.INFO)

    # Force-reimport the adapter so module-state (_PATCHED) resets between
    # parameterised invocations.
    for k in list(sys.modules.keys()):
        if k.startswith(f"synapse.frameworks.{framework_name}"):
            del sys.modules[k]

    try:
        from synapse.install import _ensure_framework_loaded, _FRAMEWORK_REGISTRY
        _ensure_framework_loaded(framework_name)
        fn = _FRAMEWORK_REGISTRY.get(framework_name)
        if fn is None:
            captured.append(
                f"WARNING synapse.install: framework {framework_name!r} not in registry"
            )
        else:
            fn({})
    finally:
        syn_logger.removeHandler(handler)
        syn_logger.setLevel(prev_level)

    return captured


@pytest.mark.parametrize(("framework", "pip_module"), ADAPTERS)
def test_adapter_patches_real_sdk(framework: str, pip_module: str) -> None:
    """If the underlying SDK is installed, the adapter must successfully
    patch it — proven by an INFO log containing `patched` and the absence
    of `could not find`."""
    try:
        importlib.import_module(pip_module)
    except ImportError:
        pytest.skip(f"{pip_module} not installed in this env; skipping adapter check")

    logs = _capture_install_logs(framework)
    joined = " ".join(logs).lower()

    has_patched = "patched" in joined
    has_could_not_find = "could not find" in joined or "not yet shipped" in joined

    if has_could_not_find:
        pytest.fail(
            f"Adapter {framework!r} reported 'could not find' against the real "
            f"{pip_module} SDK. The dispatch path it probes for likely no longer "
            f"exists in the current SDK version. Logs:\n  "
            + "\n  ".join(logs)
        )
    # Some adapters (e.g. langgraph callback-style) don't log "patched" — they
    # log "callback ready". Accept either as success.
    if not (has_patched or "callback ready" in joined or "registered" in joined):
        pytest.fail(
            f"Adapter {framework!r} did not log 'patched' or 'callback ready' "
            f"against the real {pip_module} SDK. Possibly a silent failure. Logs:\n  "
            + "\n  ".join(logs)
        )
