# Install

```bash
pip install synapse-protocol-py
```

That's it for the audit path. For live coordination:

```bash
pip install 'synapse-protocol-py[live]'
synapse up
```

For framework-specific extras, install your framework alongside:

```bash
pip install 'synapse-protocol-py[live]' autogen-agentchat crewai langchain-core openai-agents pydantic-ai smolagents strands-agents agno llama-index-core google-adk
```
