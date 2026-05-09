# Adapter health gate

Every adapter is verified against the real published SDK by `tests/test_adapter_health.py` on every release.

**11 of 11 pass** as of v0.2.2.

| Framework | Real SDK package | Status |
|---|---|---|
| AutoGen | autogen-agentchat 0.7.5 | ✓ |
| CrewAI | crewai 1.14.4 | ✓ |
| LangChain | langchain-core 0.3 | ✓ |
| LangGraph | langgraph (latest) | ✓ |
| OpenAI Agents | openai-agents 0.17.0 | ✓ |
| Pydantic AI | pydantic-ai 1.92.0 | ✓ |
| smolagents | smolagents 1.24.0 | ✓ |
| Strands Agents | strands-agents (latest) | ✓ |
| Agno | agno 2.6.5 | ✓ |
| LlamaIndex | llama-index-core 0.11+ | ✓ |
| Google ADK | google-adk (latest) | ✓ |

Run locally:

```bash
cd sdk-python
pytest tests/test_adapter_health.py -v
```

This is institutional memory of the May-2026 incident where Strands and pydantic_ai shipped silently broken because their smoke tests used hand-built fakes. Future API drift surfaces at test time.
