# adapters/hosted

Hosted-LLM bridge adapters (Anthropic, OpenAI, Gemini, etc.). These let
Synapse route through your existing hosted-API LLM client.

See [`sdk-python/synapse/llm.py`](../../sdk-python/synapse/llm.py) for the
`set_llm` / `from_anthropic` / `from_openai` / `from_litellm` /
`auto_llm` entry points (BYO-LLM). The 10 framework adapters shipped in
v0.2.8 are listed in the top-level [`README.md`](../../README.md).

For the current roadmap, see [`docs/roadmap/README.md`](../../docs/roadmap/README.md).
