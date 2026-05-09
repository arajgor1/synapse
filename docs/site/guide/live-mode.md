# Live mode

```bash
pip install 'synapse-protocol[live]'
synapse up
python -c "import synapse; synapse.install(framework='langgraph')"
```

Every tool call across LangGraph (or any of the 11 supported frameworks) emits a Synapse INTENTION envelope. CONFLICT envelopes fire when two agents collide on the same scope.

Replace `framework='langgraph'` with any of: `autogen`, `crewai`, `langchain`, `openai_agents`, `pydantic_ai`, `smolagents`, `strands`, `agno`, `llama_index`, `google_adk`.
