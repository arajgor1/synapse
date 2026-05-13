# adapters/local

Local-LLM bridge adapters. The v0.2.8 deep-NLA module for self-hosted
HuggingFace transformers lives at
[`sdk-python/synapse/llm_nla_hf.py`](../../sdk-python/synapse/llm_nla_hf.py) —
captures logits, attention weights, and hidden-state norms per token,
emitted as THOUGHT envelopes.

For Ollama / vLLM / local OpenAI-compat servers, use the OpenAI bridge
in [`sdk-python/synapse/llm.py`](../../sdk-python/synapse/llm.py) pointed
at your local endpoint.

For the current roadmap, see [`docs/roadmap/README.md`](../../docs/roadmap/README.md).
