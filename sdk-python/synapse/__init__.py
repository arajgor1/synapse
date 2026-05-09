"""Synapse — coordination + observability + safety layer for multi-agent AI stacks.

v0.1: protocol substrate (envelopes, bus, state graph, router, integrations).
v0.2: audit + universal SDK + BYO-LLM + framework adapters + merge policies.

The 30-second hello-world (works against any framework that emits OTel,
LangSmith, or JSONL traces):

    pip install synapse-protocol
    synapse audit ./your-traces.json   # see the silent conflicts you missed

Live integration into your own stack:

    import synapse
    from anthropic import AsyncAnthropic
    synapse.set_llm(synapse.from_anthropic(AsyncAnthropic()))
    synapse.install(framework="langgraph")  # auto-detects and hooks in

    # Or use the universal context-manager API directly:
    async with synapse.intend(
        scope=["repo.fs.auth.py:w"], agent="me",
    ) as i:
        if i.has_conflicts:
            await i.pivot()
        await my_tool_call()
"""

from synapse.agent import Agent
from synapse.messages import (
    Belief,
    Block,
    Conflict,
    CostReport,
    Envelope,
    Intention,
    MessageType,
    Pivot,
    Resolution,
    Thought,
)

# v0.2 universal SDK + BYO-LLM
from synapse.intend import intend, IntentionHandle
from synapse.install import install, register_framework
from synapse.llm import (
    set_llm,
    get_llm,
    is_configured as llm_is_configured,
    from_anthropic,
    from_openai,
    from_langchain,
    from_litellm,
    auto_llm,
)
from synapse.policies import (
    MergePolicy,
    MergeAction,
    MergeDecision,
    SynapseConflict,
)
# v0.2 week 5: BELIEFs as a public surface
from synapse.beliefs import (
    emit_belief,
    list_divergences,
    divergences_for_key,
)
# v0.2.2: per-task agent attribution via contextvars
# (replaces the SYNAPSE_AGENT_ID env-var race documented in
# bench/REAL_LIFE_TESTING.md Bug 1)
from synapse.agent_context import (
    set_agent_context,
    reset_agent_context,
    with_agent,
    current_agent_id,
)

__version__ = "0.2.2a2"
__all__ = [
    # v0.1 surface
    "Agent",
    "Envelope",
    "MessageType",
    "Intention",
    "Conflict",
    "Block",
    "Pivot",
    "Belief",
    "Thought",
    "Resolution",
    "CostReport",
    # v0.2 surface
    "intend",
    "IntentionHandle",
    "install",
    "register_framework",
    "set_llm",
    "get_llm",
    "llm_is_configured",
    "from_anthropic",
    "from_openai",
    "from_langchain",
    "from_litellm",
    "auto_llm",
    # v0.2 week 4: policies
    "MergePolicy",
    "MergeAction",
    "MergeDecision",
    "SynapseConflict",
    # v0.2 week 5: beliefs
    "emit_belief",
    "list_divergences",
    "divergences_for_key",
    # v0.2.2: agent context (per-task ContextVar attribution)
    "set_agent_context",
    "reset_agent_context",
    "with_agent",
    "current_agent_id",
    "__version__",
]
