"""Native tier adapters — direct control over the inference engine, including
the KV cache. Mid-stream injection on this tier is a true KV-append: pause
generation, append signal tokens to the cache, resume. No work discarded.

Phase 3: vLLM (via Modal serverless GPU). Future: SGLang, TGI, llama.cpp.

The Modal-hosted vLLM adapter sits in this tier rather than 'local' because
the Synapse SDK gets first-class control over generation lifecycle through
Modal's RPC mechanism, not just a black-box HTTP API.
"""

from synapse.adapters.native.vllm_modal_adapter import VLLMModalAdapter

__all__ = ["VLLMModalAdapter"]
