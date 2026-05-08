"""Smoke test for the Strands adapter.

Goal: prove that ``synapse.install(framework='strands')`` discovers and
patches the Strands SDK's tool-dispatch entry point WITHOUT requiring
the real Strands SDK to be installed. We register a fake module with
the canonical structure the adapter probes for, run install, and verify
the dispatch is wrapped.

This is the same kind of fixture-driven test the LangGraph and CrewAI
adapters have — does not burn LLM tokens, does not need Modal.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import types

# Build a fake `strands.tools.handler` module whose ToolHandler class
# exposes an async handle_tool_call. After install, that method must
# be wrapped (we detect via the .__wrapped__ marker the wrapper sets).


def _build_fake_strands_module():
    strands = types.ModuleType("strands")
    strands_tools = types.ModuleType("strands.tools")
    strands_tools_handler = types.ModuleType("strands.tools.handler")

    class ToolUse:
        def __init__(self, name, input):
            self.name = name
            self.input = input

    class FakeAgent:
        def __init__(self, name="strands-test-agent"):
            self.name = name

    class ToolHandler:
        async def handle_tool_call(self, tool_use, agent, *args, **kwargs):
            return {"status": "ok", "tool": tool_use.name}

    strands.Agent = FakeAgent
    strands_tools.ToolHandler = ToolHandler
    strands_tools_handler.ToolHandler = ToolHandler

    sys.modules["strands"] = strands
    sys.modules["strands.tools"] = strands_tools
    sys.modules["strands.tools.handler"] = strands_tools_handler
    return ToolHandler, ToolUse, FakeAgent


def run_strands_smoke():
    print("=== Strands adapter smoke test ===")

    ToolHandler, ToolUse, FakeAgent = _build_fake_strands_module()

    # Force-reimport the synapse adapter so its module-state (_PATCHED)
    # resets between test runs in the same process.
    for k in list(sys.modules.keys()):
        if k.startswith("synapse.frameworks.strands"):
            del sys.modules[k]

    # Register the framework
    from synapse.frameworks import strands as strands_adapter  # noqa: F401

    # Trigger install via the canonical entry point
    from synapse.install import _ensure_framework_loaded
    _ensure_framework_loaded("strands")

    # The adapter calls _install_strands when register_framework fires.
    # Manually invoke to mirror what install() does.
    from synapse.install import _FRAMEWORK_REGISTRY  # type: ignore[attr-defined]
    install_fn = _FRAMEWORK_REGISTRY.get("strands")
    if install_fn is None:
        print("  FAIL: strands not in framework registry")
        return False
    install_fn({})

    # Verify the handler was wrapped
    if not hasattr(ToolHandler.handle_tool_call, "__wrapped__"):
        print("  FAIL: ToolHandler.handle_tool_call is not wrapped (no __wrapped__ marker)")
        return False
    print("  ✓ ToolHandler.handle_tool_call is wrapped")

    # Try dispatching through the wrapped path WITHOUT any Synapse runtime —
    # this should fall through cleanly because the tool is non-write.
    handler = ToolHandler()
    use = ToolUse(name="search_docs", input={"query": "test"})  # read-only tool
    agent = FakeAgent()
    try:
        result = asyncio.run(handler.handle_tool_call(use, agent))
        if isinstance(result, dict) and result.get("status") == "ok":
            print(f"  ✓ non-write tool falls through: {result}")
        else:
            print(f"  FAIL: unexpected result for non-write tool: {result!r}")
            return False
    except Exception as e:
        print(f"  FAIL: dispatch raised on non-write: {type(e).__name__}: {e}")
        return False

    # Verify scope inference + is_write detection on a write tool
    from synapse.audit.events import is_write, AuditEvent
    from synapse.audit.scope_inference import infer_scope
    write_use = ToolUse(name="edit_file", input={"path": "src/auth.py", "content": "..."})
    fake_ev = AuditEvent(
        trace_id="t", span_id="s", agent_id="a", session_id="sess",
        tool_name=write_use.name, tool_args=write_use.input,
        ts_start_ms=0, ts_end_ms=0,
    )
    if not is_write(fake_ev):
        print("  FAIL: edit_file with path arg should be detected as write")
        return False
    scope = infer_scope(fake_ev)
    if not scope or "repo.fs.src/auth.py:w" not in scope:
        print(f"  FAIL: scope inference returned {scope}, expected ['repo.fs.src/auth.py:w']")
        return False
    print(f"  ✓ scope inference for edit_file: {scope}")

    print("\n=== Strands smoke test PASSED ===")
    return True


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "sdk-python")
    ok = run_strands_smoke()
    sys.exit(0 if ok else 1)
