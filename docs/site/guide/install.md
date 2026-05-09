# Install

```bash
pip install synapse-protocol
```

That's it for the audit path. For live coordination:

```bash
pip install 'synapse-protocol[live]'
synapse up
```

For framework-specific extras, install your framework alongside:

```bash
pip install 'synapse-protocol[live]' autogen-agentchat crewai langchain-core openai-agents pydantic-ai smolagents strands-agents agno llama-index-core google-adk
```
