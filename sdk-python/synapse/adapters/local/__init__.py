"""Local-API tier adapters — talk to a locally-running inference server
that exposes a context/cache hook so we can resume generation efficiently.

Phase 3: Ollama. Future: LM Studio, OpenRouter (where backend supports it).
"""

from synapse.adapters.local.ollama_adapter import OllamaAdapter

__all__ = ["OllamaAdapter"]
