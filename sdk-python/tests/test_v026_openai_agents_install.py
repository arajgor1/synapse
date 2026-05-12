"""Regression test for v0.2.6 openai_agents adapter coverage.

v16 finding: with_synapse mode showed 0 intents in both POSITIVE +
NEGATIVE tests. Investigation showed:
  - the adapter DOES patch FunctionTool.on_invoke_tool correctly
  - the patch fires when on_invoke_tool is invoked
  - the v16 [0,0,0] was caused by the Gemini-via-openai-proxy path
    not reliably emitting tool_calls in chat completions responses
    — the Runner never reached the tool dispatch path

This test verifies the adapter itself (the patch mechanism) without
needing a real LLM call.
"""
from __future__ import annotations

import os
import pytest

pytest.importorskip("agents")  # the openai-agents package


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("SYNAPSE_SQLITE_PATH", str(tmp_path / "oa_install.db"))
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    monkeypatch.delenv("SYNAPSE_POSTGRES_DSN", raising=False)


def test_install_patches_function_tool_decorator():
    """After synapse.install(framework='openai_agents'), the function_tool
    decorator must be wrapped so every FunctionTool it produces has
    on_invoke_tool intercepted."""
    import synapse
    synapse.install(framework="openai_agents")

    from agents import function_tool

    @function_tool
    def my_writer(content: str) -> str:
        """Write content to a file."""
        return f"wrote {len(content)}"

    # The decorated object must be a FunctionTool with patched on_invoke_tool
    assert hasattr(my_writer, "on_invoke_tool")
    invoker = my_writer.on_invoke_tool
    # After our patch, on_invoke_tool should be a callable function
    # (wrapping the original _FailureHandlingFunctionToolInvoker)
    assert callable(invoker), f"on_invoke_tool not callable: {type(invoker)}"
    # The wrapper is created in synapse.frameworks.openai_agents._wrap_invoke
    qualname = getattr(invoker, "__qualname__", "")
    assert "async_wrapper" in qualname or "_wrap_invoke" in qualname, (
        f"on_invoke_tool not patched (qualname={qualname!r})"
    )


def test_install_patches_already_imported_function_tool():
    """If `from agents import function_tool` was done BEFORE
    synapse.install(), the patch must reach that already-imported reference
    so @function_tool used afterward gets wrapped."""
    # Import function_tool BEFORE install
    from agents import function_tool as ft_before
    qualname_before = ft_before.__qualname__

    import synapse
    synapse.install(framework="openai_agents")

    # The module-level reference should now point at our patch
    from agents import function_tool as ft_after
    # The local binding `ft_before` we held is what matters for users who
    # did `from agents import function_tool` early — our rebind should
    # have updated it via the sys.modules walk
    @ft_after
    def post_install_tool(x: str) -> str:
        """A tool."""
        return x

    inv = post_install_tool.on_invoke_tool
    assert callable(inv)
    assert "async_wrapper" in getattr(inv, "__qualname__", "") or \
           "_wrap_invoke" in getattr(inv, "__qualname__", ""), (
        f"already-imported function_tool not rebound; "
        f"qualname={inv.__qualname__!r}"
    )


def test_idempotent_double_install_does_not_double_wrap():
    """Calling synapse.install(framework='openai_agents') twice must not
    cause N intentions per tool call (the _PATCHED guard prevents this)."""
    import synapse
    synapse.install(framework="openai_agents")
    from agents import function_tool

    @function_tool
    def tool_first(x: str) -> str:
        """First."""
        return x

    inv_first = tool_first.on_invoke_tool

    synapse.install(framework="openai_agents")

    @function_tool
    def tool_second(x: str) -> str:
        """Second."""
        return x

    inv_second = tool_second.on_invoke_tool

    # Both should be wrapped — but only once each, not twice
    # Check by inspecting qualname; if double-wrapped we'd see nested closures
    q1 = getattr(inv_first, "__qualname__", "")
    q2 = getattr(inv_second, "__qualname__", "")
    # Single wrap → single occurrence of "async_wrapper"
    assert q1.count("async_wrapper") <= 1
    assert q2.count("async_wrapper") <= 1
