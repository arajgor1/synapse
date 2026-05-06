# InferenceAdapter Contract

> The single most important interface in Synapse. Wraps an LLM backend in a uniform shape so the SDK and runtime can drive any backend (self-hosted vLLM, Ollama, hosted Claude/GPT/Gemini) identically.

## Status

`v1.0` — locked at Phase 0. Changes after Phase 0 land as additive ADRs.

## The Three Tiers

| Tier | Backends | Mechanism | Overhead |
|---|---|---|---|
| `native` | vLLM, SGLang, TGI, llama.cpp | True KV-cache append (pause / append / resume) | ~1.05x |
| `local_api` | Ollama, LM Studio | Resume via exposed context tokens | ~1.08x |
| `hosted` | Anthropic, OpenAI, Gemini | Cached restart with prompt caching | ~1.10–1.30x |

## Interface

```python
from typing import Protocol, AsyncIterator
from dataclasses import dataclass

@dataclass
class BackendCapabilities:
    backend_id: str
    tier: str  # "native" | "local_api" | "hosted"
    supports_midstream_inject: bool
    supports_partial_preservation: bool
    is_reasoning_model: bool
    prompt_cache_available: bool
    avg_overhead_per_signal: float
    multi_tenant_isolation: str  # "process" | "request_id" | "none"

@dataclass
class StreamHandle:
    """Opaque handle to an in-flight generation. Adapter-specific contents."""
    request_id: str
    original_messages: list[dict]
    params: dict

@dataclass
class Token:
    text: str
    is_thinking: bool = False  # True during reasoning-model thinking phases

class InferenceAdapter(Protocol):
    capabilities: BackendCapabilities

    async def start_stream(
        self,
        messages: list[dict],
        params: dict,
    ) -> StreamHandle:
        """Begin a streaming generation. Returns a handle for subsequent operations."""

    async def read_tokens(
        self, handle: StreamHandle
    ) -> AsyncIterator[Token]:
        """Async iterator over tokens as they generate. Caller may stop iterating
        at any time without cancelling the underlying request."""

    async def inject_and_continue(
        self,
        handle: StreamHandle,
        injection: str,
        instruction: str = "Continue, accounting for the above.",
    ) -> StreamHandle:
        """Append context mid-generation and resume. The KEY method.

        Native: true KV-cache append (no work discarded).
        Local-API: resume from exposed context tokens.
        Hosted: cancel + restart with prompt-cached prefix + partial output + injection.

        Returns a new (or same) handle representing the continued stream.
        Adapter MUST emit a COST_REPORT after the operation completes."""

    async def cancel(self, handle: StreamHandle) -> str:
        """Cancel the in-flight generation. Returns whatever was generated before
        cancellation. May return empty string if the backend doesn't support
        partial preservation."""
```

## Capability Flags

### `supports_midstream_inject`

True if `inject_and_continue` works during active generation. **False for reasoning models during their thinking phase** — signals queue and inject at the next visible-output boundary.

### `supports_partial_preservation`

True if partial output is preserved when a stream is cancelled. Affects routing economics: backends without preservation pay full restart cost, so the router raises injection thresholds for them.

| Backend | Partial preservation |
|---|---|
| vLLM (native) | Yes — generation paused, not cancelled |
| Ollama | Yes — context exposed as tokens |
| Anthropic | Yes — `MessageStreamEvent` deltas preserved on abort |
| OpenAI | Yes — chunk deltas preserved on abort |
| Gemini | Inconsistent across SDK versions; adapter probes at startup |

### `multi_tenant_isolation`

How the adapter isolates tenants in shared deployments:

- `process` — each agent has its own backend process (e.g., separate vLLM instance). Strongest isolation, highest resource cost.
- `request_id` — shared backend, ownership validated per request. Adapter prefixes every request with `tenant:agent:request` and rejects cross-tenant access at the boundary.
- `none` — single-tenant only. Multi-tenant deployments must not use this adapter.

**v1.0 ships `process` mode only.** `request_id` mode lands in v1.1.

## Reasoning-Model Behavior

When `is_reasoning_model: true`:

1. The adapter's token stream tags tokens with `is_thinking: bool`.
2. While `is_thinking == true`, the SDK queues incoming signals — no injection attempted.
3. When `is_thinking` transitions to `false` (thinking ends, visible output begins) or the response completes, queued signals inject at that boundary.
4. The adapter emits a `THOUGHT` boundary marker so the coordinator knows when injection becomes possible.

Practical implication: reasoning-model agents have decision points roughly per-turn (10–60 seconds), not per-token. The protocol still works — coordination happens at turn boundaries. Mid-thinking interruption is not supported in v1.

## Cost Reporting

After every `inject_and_continue` call, the adapter MUST emit a `COST_REPORT` containing:

- `mechanism` — one of `native_kv_append`, `local_api_context_resume`, `hosted_cached_restart`
- `tokens_billed` — total
- `tokens_cached` — portion that hit the prompt cache (hosted only)
- `wall_clock_ms` — end-to-end latency
- `estimated_usd` — calculated by the SDK from current pricing

This drives the coordinator's adaptive routing thresholds and the developer-facing cost dashboard.

## Failure Modes

The adapter MUST handle:

- **Backend unreachable**: raise `BackendUnavailable`. The SDK falls back to no-coordination mode for the affected agent until the backend recovers.
- **Cancel race**: if `inject_and_continue` is called on a handle that just finished naturally, return the completed result without error.
- **Capability mismatch**: if asked to do something the backend doesn't support (e.g., `inject_and_continue` on a reasoning model during thinking), raise `UnsupportedCapability`. The router should never make this call given correct capabilities, so this is a defensive check.

## Implementing a New Adapter

1. Implement the `InferenceAdapter` protocol.
2. Populate `BackendCapabilities` accurately. **Lying about capabilities breaks the router.**
3. Run the standardized adapter test suite: `synapse adapter-test <your-adapter>`.
4. Run the benchmark: `synapse bench --backend <id>` and contribute results to `bench/results/`.
5. Open a PR with the adapter, capability declaration, and benchmark output.

## Reference Implementations

- `adapters/native/vllm.py` — first to land in Phase 3.
- `adapters/local/ollama.py` — second.
- `adapters/hosted/anthropic.py` — first overall (Phase 1).
- `adapters/hosted/openai.py` — Phase 5.
- `adapters/hosted/gemini.py` — Phase 5.
