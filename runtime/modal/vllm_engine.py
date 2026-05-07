"""Modal serverless GPU engine for Synapse native-tier adapter.

Uses real **vLLM** for production-grade throughput. Engine state per request:
- A stateful container holding a loaded vLLM `AsyncLLMEngine`
- vLLM handles per-request KV cache isolation natively (request_id keyed)
- Streaming via `engine.generate(prompt, sampling_params, request_id)` async iterator
- Mid-stream cancel via `engine.abort(request_id)` — true cache-preserving abort

The image base is the upstream `vllm/vllm-openai` Docker image, which has
torch + CUDA + vLLM + xformers + triton pre-installed and pre-compiled.
This avoids the 5-10min pip-install cold build that bombs out on Modal's
build timeout.

Cost discipline:
- T4 GPU on Modal serverless: ~$0.000204/sec (~$0.74/hour).
- scaledown_window=30s -> container shuts down 30s after last call.
- Model: Qwen2.5-0.5B-Instruct (~1GB, loads in <30s on T4).

Deploy:
    modal deploy runtime/modal/vllm_engine.py

Smoke test:
    modal run runtime/modal/vllm_engine.py::smoke_test
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, AsyncIterator

import modal

# ---------------------------------------------------------------------------
APP_NAME = "synapse-vllm"
HF_VOLUME = modal.Volume.from_name("synapse-hf-cache", create_if_missing=True)
HF_CACHE_DIR = "/cache/hf"
DEFAULT_MODEL = os.environ.get("SYNAPSE_VLLM_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")
DEFAULT_GPU = os.environ.get("SYNAPSE_VLLM_GPU", "T4")

# Use the upstream vLLM image — torch + CUDA + vllm + xformers all baked in
image = (
    modal.Image.from_registry(
        "vllm/vllm-openai:v0.6.3",
        add_python="3.11",
    )
    .env({
        "HF_HOME": HF_CACHE_DIR,
        "TRANSFORMERS_OFFLINE": "0",
        "VLLM_WORKER_MULTIPROC_METHOD": "spawn",
    })
)

app = modal.App(APP_NAME, image=image)


@app.cls(
    gpu=DEFAULT_GPU,
    volumes={HF_CACHE_DIR: HF_VOLUME},
    scaledown_window=30,
    timeout=600,
)
class VLLMEngine:
    """Stateful container hosting a real vLLM AsyncLLMEngine.

    Each container instance runs ONE vLLM async engine. Multiple Synapse
    streams multiplex onto it via vLLM's request_id-keyed `add_request`
    mechanism — vLLM handles per-request KV cache isolation natively.
    """

    @modal.enter()
    def load_engine(self) -> None:
        from vllm import AsyncEngineArgs, AsyncLLMEngine

        self.model_name = DEFAULT_MODEL
        engine_args = AsyncEngineArgs(
            model=self.model_name,
            dtype="auto",
            gpu_memory_utilization=0.85,
            max_model_len=4096,
            enforce_eager=True,           # faster cold-start on small models
            disable_log_stats=True,
        )
        self.engine = AsyncLLMEngine.from_engine_args(engine_args)
        # Track active request_ids so cancel() can be a no-op safely
        self._active: set[str] = set()

    @modal.method()
    async def generate_stream(
        self,
        request_id: str,
        prompt: str,
        max_tokens: int = 256,
        temperature: float = 0.7,
        prepend_partial: str | None = None,
    ):
        """Stream tokens via vLLM's native async generator.

        Yields dicts: {"delta": str, "finished": bool, "usage"?: {...}}.
        """
        from vllm import SamplingParams

        full_prompt = prompt
        if prepend_partial:
            # Anchor the partial output as already-emitted assistant text
            full_prompt = (
                f"{prompt}\n[ASSISTANT_PARTIAL]\n{prepend_partial}\n[CONTINUE]\n"
            )

        sampling = SamplingParams(
            max_tokens=max_tokens,
            temperature=temperature,
        )

        self._active.add(request_id)
        last_text = ""
        prompt_tokens = 0
        completion_tokens = 0
        try:
            async for output in self.engine.generate(full_prompt, sampling, request_id):
                # vLLM yields RequestOutput with cumulative .outputs[0].text
                if output.prompt_token_ids and not prompt_tokens:
                    prompt_tokens = len(output.prompt_token_ids)
                if not output.outputs:
                    continue
                cur_text = output.outputs[0].text
                delta = cur_text[len(last_text):]
                last_text = cur_text
                if delta:
                    completion_tokens = len(output.outputs[0].token_ids or [])
                    yield {"delta": delta, "finished": False}
                if output.finished:
                    break
        finally:
            self._active.discard(request_id)
            yield {
                "delta": "",
                "finished": True,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                },
            }

    @modal.method()
    async def cancel(self, request_id: str) -> None:
        if request_id in self._active:
            try:
                await self.engine.abort(request_id)
            except Exception:
                pass
            self._active.discard(request_id)

    @modal.method()
    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "engine": "vllm",
            "model": getattr(self, "model_name", DEFAULT_MODEL),
            "gpu": DEFAULT_GPU,
            "active_requests": len(getattr(self, "_active", set())),
        }


# ---------------------------------------------------------------------------
@app.local_entrypoint()
def smoke_test(prompt: str = "Say hi in three words.", max_tokens: int = 16) -> None:
    engine = VLLMEngine()
    print(f"Model: {DEFAULT_MODEL}, GPU: {DEFAULT_GPU}")
    text = ""
    rid = str(uuid.uuid4())
    started = time.time()
    for chunk in engine.generate_stream.remote_gen(
        request_id=rid, prompt=prompt, max_tokens=max_tokens
    ):
        delta = chunk.get("delta")
        if delta:
            text += delta
            print(delta, end="", flush=True)
        if chunk.get("finished"):
            break
    elapsed = time.time() - started
    print(f"\n\n--- final ({elapsed:.1f}s): {text!r}")
