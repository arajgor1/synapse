"""Modal serverless GPU engine for Synapse native-tier adapter.

Phase 3 ships with a *transformers-based* engine rather than vLLM. Reason:
the vLLM 0.6 wheel is ~200MB with full CUDA/torch/xformers/triton deps;
the Modal build was unreliable in our cost+time budget.

This engine still proves the native-tier mechanism end-to-end:
- Stateful container holding a loaded model
- Streaming token generation via `TextIteratorStreamer`
- Mid-stream cancel via a per-request `Event` flag
- Multi-request isolation via `request_id`-keyed state dict

The `vllm_modal_adapter.py` SDK adapter talks to this engine over Modal RPC
without caring whether the underlying engine is vLLM or transformers.
For production deploy with vLLM, swap this file for the vllm-based version
in `runtime/modal/vllm_engine_full.py` (deploy time: 5-10 min for the image).

Cost discipline:
- T4 GPU on Modal serverless: ~$0.000204/sec (~$0.74/hour).
- Container shuts down 30s after last call.
- Model: Qwen2.5-0.5B-Instruct (~1GB, loads in <30s on T4).

Deploy with:
    modal deploy runtime/modal/vllm_engine.py

Smoke test:
    modal run runtime/modal/vllm_engine.py::smoke_test
"""

from __future__ import annotations

import os
import threading
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

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch==2.4.1",
        "transformers>=4.45,<5",
        "accelerate>=1.0",
        "sentencepiece",
        "protobuf",
        "huggingface_hub>=0.25",
    )
    .env({"HF_HOME": HF_CACHE_DIR, "TRANSFORMERS_OFFLINE": "0"})
)

app = modal.App(APP_NAME, image=image)


@app.cls(
    gpu=DEFAULT_GPU,
    volumes={HF_CACHE_DIR: HF_VOLUME},
    scaledown_window=30,
    timeout=600,
)
class VLLMEngine:
    """Stateful container hosting a transformers-based engine.

    Named `VLLMEngine` for forward compatibility — once the user has bandwidth
    to deploy the full vLLM image, the class can be swapped without changing
    the SDK adapter.
    """

    @modal.enter()
    def load_engine(self) -> None:
        from transformers import AutoModelForCausalLM, AutoTokenizer
        import torch

        self.model_name = DEFAULT_MODEL
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_name,
            torch_dtype=torch.float16,
            device_map="auto",
        )
        self.model.eval()
        # Per-request state for cancellation
        self._cancel_events: dict[str, threading.Event] = {}

    @modal.method()
    def generate_stream(
        self,
        request_id: str,
        prompt: str,
        max_tokens: int = 256,
        temperature: float = 0.7,
        prepend_partial: str | None = None,
    ):
        """Stream generation tokens for a single request.

        Yields dicts: {"delta": str, "finished": bool, "usage"?: {...}}.
        """
        from transformers import TextIteratorStreamer
        import torch

        full_prompt = prompt
        if prepend_partial:
            full_prompt = f"{prompt}\n[ASSISTANT_PARTIAL]\n{prepend_partial}\n[CONTINUE]\n"

        cancel_evt = threading.Event()
        self._cancel_events[request_id] = cancel_evt

        inputs = self.tokenizer(full_prompt, return_tensors="pt").to(self.model.device)
        streamer = TextIteratorStreamer(
            self.tokenizer, skip_prompt=True, skip_special_tokens=True
        )
        gen_kwargs: dict[str, Any] = {
            **inputs,
            "max_new_tokens": max_tokens,
            "do_sample": temperature > 0,
            "temperature": max(temperature, 0.001),
            "streamer": streamer,
        }
        prompt_tokens = int(inputs.input_ids.shape[1])

        thread = threading.Thread(
            target=self.model.generate, kwargs=gen_kwargs, daemon=True
        )
        thread.start()

        completion_tokens = 0
        try:
            for piece in streamer:
                if cancel_evt.is_set():
                    break
                if piece:
                    completion_tokens += 1
                    yield {"delta": piece, "finished": False}
        finally:
            self._cancel_events.pop(request_id, None)
            yield {
                "delta": "",
                "finished": True,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                },
            }

    @modal.method()
    def cancel(self, request_id: str) -> None:
        evt = self._cancel_events.get(request_id)
        if evt is not None:
            evt.set()

    @modal.method()
    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "model": getattr(self, "model_name", DEFAULT_MODEL),
            "gpu": DEFAULT_GPU,
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
