"""End-to-end attribution tests through the real framework adapters.

These tests prove the ContextVar fix actually distinguishes per-task
attribution under asyncio.gather, exercising the patched dispatch
methods in the real framework SDKs (no LLM, no Postgres — captures the
agent_id seen from inside the tool body).

The pre-fix env-var scheme produced last-writer-wins under load: both
parallel calls saw whichever value was last written to
``os.environ["SYNAPSE_AGENT_ID"]``. These tests would fail under that
implementation.
"""
from __future__ import annotations

import asyncio

import pytest

import synapse


@pytest.fixture
def fresh_install():
    """Re-import adapter modules to ensure patches survive across tests."""
    yield
    # No teardown — adapter patches are intentionally process-global.


@pytest.mark.asyncio
async def test_langchain_adapter_distinguishes_attributions(fresh_install):
    """Two parallel ainvoke()s, each in its own with_agent() block, must
    see distinct agent_ids inside the tool body."""
    pytest.importorskip("langchain_core")
    from langchain_core.tools import StructuredTool

    synapse.install(framework="langchain")

    captured: list[tuple[str, str]] = []

    def edit_file(path: str, content: str) -> str:
        # Read the agent_id Synapse resolves AT TOOL-CALL TIME.
        captured.append((synapse.current_agent_id(), content))
        return f"ok: {path}"

    tool = StructuredTool.from_function(
        edit_file, name="edit_file", description="x"
    )

    async def call_as(name: str, content: str):
        with synapse.with_agent(name):
            return await tool.ainvoke({"path": "app/models.py", "content": content})

    await asyncio.gather(
        call_as("alice", "A"),
        call_as("bob", "B"),
    )

    seen_agents = {c[0] for c in captured}
    assert seen_agents == {"alice", "bob"}, (
        f"Last-writer-wins collapse: {captured}"
    )


@pytest.mark.asyncio
async def test_langchain_attribution_under_high_concurrency(fresh_install):
    """20 concurrent invocations — every one must see its own agent_id."""
    pytest.importorskip("langchain_core")
    from langchain_core.tools import StructuredTool

    synapse.install(framework="langchain")

    captured: list[tuple[str, int]] = []

    def edit_file(path: str, content: str) -> str:
        captured.append((synapse.current_agent_id(), int(content)))
        return "ok"

    tool = StructuredTool.from_function(
        edit_file, name="edit_file", description="x"
    )

    async def call_as(i: int):
        with synapse.with_agent(f"agent_{i:02d}"):
            await tool.ainvoke({"path": f"f{i}.py", "content": str(i)})

    await asyncio.gather(*[call_as(i) for i in range(20)])

    misattributed = [
        (agent, idx) for agent, idx in captured
        if agent != f"agent_{idx:02d}"
    ]
    assert misattributed == [], (
        f"Misattribution under load: {misattributed} of {len(captured)} calls"
    )


@pytest.mark.asyncio
async def test_autogen_adapter_distinguishes_attributions(fresh_install, monkeypatch):
    """Same race for AutoGen FunctionTool.run.

    Note: autogen-core 0.7.5's FunctionTool runs sync tools via
    ``loop.run_in_executor(None, ...)`` which does NOT propagate
    contextvars to the worker thread. So we cannot read agent_id from
    inside the tool body. Instead we spy on the wrapper's resolver
    (which DOES run on the caller task with the ContextVar set) — this
    is the value that gets attached to the emitted INTENTION envelope,
    which is the only attribution that matters for downstream auditing.
    """
    pytest.importorskip("autogen_core")
    from autogen_core.tools import FunctionTool
    from autogen_core import CancellationToken
    from synapse.frameworks import autogen as autogen_adapter

    synapse.install(framework="autogen")

    seen_in_wrapper: list[str] = []
    real_resolver = autogen_adapter._resolve_agent_id_from_context

    def spy(ctx):
        out = real_resolver(ctx)
        seen_in_wrapper.append(out)
        return out

    monkeypatch.setattr(autogen_adapter, "_resolve_agent_id_from_context", spy)

    def edit_file(path: str, content: str) -> str:
        return f"ok: {path}"

    tool = FunctionTool(edit_file, name="edit_file", description="Edit a file")

    async def call_as(name: str, content: str):
        args = tool.args_type()(path="app/models.py", content=content)
        with synapse.with_agent(name):
            return await tool.run(args, CancellationToken())

    await asyncio.gather(
        call_as("alice", "A"),
        call_as("bob", "B"),
    )

    seen_agents = set(seen_in_wrapper)
    assert seen_agents == {"alice", "bob"}, (
        f"Wrapper resolver collapsed under gather: {seen_in_wrapper}"
    )
