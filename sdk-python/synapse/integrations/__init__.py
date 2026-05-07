"""Synapse framework integrations.

These are NOT inference adapters (those wrap LLMs). These adapt agent
*runtimes* — LangGraph workflows, CrewAI crews — so they emit Synapse
protocol messages around their existing execution model.

Design rule: integrations add coordination *around* the framework's existing
execution. They do not replace any framework primitive. A LangGraph workflow
that has never heard of Synapse keeps running unchanged; adding a single
decorator/wrapper opts a node into coordination.
"""

from synapse.integrations.langgraph_integration import synapse_node
from synapse.integrations.crewai_integration import synapse_task

__all__ = ["synapse_node", "synapse_task"]
