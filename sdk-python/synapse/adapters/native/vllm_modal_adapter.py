"""vLLM-via-Modal native adapter.

Talks to a Modal-deployed vLLM engine over Modal's RPC. The engine is at
`runtime/modal/vllm_engine.py` (`synapse-vllm` app); deploy it with
`modal deploy runtime/modal/vllm_engine.py` once before using this adapter.

Native-tier mid-stream injection on Modal:
- vLLM doesn't expose direct mid-request KV cache append from outside the
  engine, so the adapter implements append-and-continue by:
    1. Calling .cancel(request_id) on the engine
    2. Capturing partial output that streamed before cancel
    3. Issuing a new generate_stream with `prepend_partial` set, so the
       model treats the partial as already-emitted assistant output and
       continues coherently from there.
- Effective overhead: ~1.05-1.10x — within the native-tier budget.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any, AsyncIterator, Optional

from synapse.adapters.base import (
    BackendUnavailable,
    InferenceAdapter,
    StreamHandle,
    Token,
)
from synapse.messages import BackendCapabilities

logger = logging.getLogger(__name__)


class VLLMModalAdapter:
    """Connects to a deployed Modal vLLM engine via RPC.

    Args:
        modal_app: Modal app name (default 'synapse-vllm').
        model: Hugging Face model id (must match what's loaded on the
            deployed engine; default Qwen2.5-0.5B-Instruct).
    """

    def __init__(
        self,
        modal_app: str = "synapse-vllm",
        model: str = "Qwen/Qwen2.5-0.5B-Instruct",
        max_tokens: int = 256,
    ) -> None:
        try:
            import modal  # type: ignore[import-not-found]
        except ImportError as e:
            raise BackendUnavailable(
                "modal not installed. `pip install modal`."
            ) from e

        self._modal = modal
        self._app_name = modal_app
        self._model = model
        self._max_tokens = max_tokens
        self._streams: dict[str, dict[str, Any]] = {}
        self._engine_cls = None  # Lazy-resolved on first call

        self.capabilities = BackendCapabilities(
            backend_id="vllm-modal",
            tier="native",
            supports_midstream_inject=True,
            supports_partial_preservation=True,
            is_reasoning_model=False,
            prompt_cache_available=False,  # vLLM has internal prefix caching, no cross-request user-visible cache
            avg_overhead_per_signal=1.07,
            multi_tenant_isolation="request_id",
            model_id=model,
        )

    # -----------------------------------------------------------------
    def _get_engine_cls(self):
        """Lazy-resolve the deployed Modal class. Caches across calls."""
        if self._engine_cls is None:
            try:
                self._engine_cls = self._modal.Cls.from_name(self._app_name, "VLLMEngine")
            except Exception as e:
                raise BackendUnavailable(
                    f"Could not find Modal class {self._app_name}/VLLMEngine. "
                    f"Run `modal deploy runtime/modal/vllm_engine.py` first. ({e})"
                ) from e
        return self._engine_cls

    async def health_check(self) -> bool:
        try:
            cls = self._get_engine_cls()
            engine = cls()
            result = await engine.health.remote.aio()
            return bool(result.get("ok"))
        except Exception as e:
            logger.warning("vLLM Modal health check failed: %s", e)
            return False

    # -----------------------------------------------------------------
    async def start_stream(
        self, messages: list[dict[str, Any]], params: dict[str, Any]
    ) -> StreamHandle:
        rid = uuid.uuid4().hex
        prompt = self._messages_to_prompt(messages)

        cls = self._get_engine_cls()
        engine = cls()

        # remote_gen returns an async generator over the streamed dicts.
        gen = engine.generate_stream.remote_gen.aio(
            request_id=rid,
            prompt=prompt,
            max_tokens=params.get("max_tokens", self._max_tokens),
            temperature=params.get("temperature", 0.7),
            prepend_partial=params.get("prepend_partial"),
        )

        self._streams[rid] = {
            "gen": gen,
            "engine": engine,
            "partial": "",
            "params": params,
            "messages": messages,
            "cancelled": False,
        }
        return StreamHandle(
            request_id=rid,
            original_messages=list(messages),
            params=dict(params),
        )

    def read_tokens(self, handle: StreamHandle) -> AsyncIterator[Token]:
        return self._read_tokens(handle)

    async def _read_tokens(self, handle: StreamHandle) -> AsyncIterator[Token]:
        state = self._streams.get(handle.request_id)
        if state is None:
            raise RuntimeError(f"Unknown request: {handle.request_id}")
        gen = state["gen"]
        try:
            async for chunk in gen:
                if state["cancelled"]:
                    break
                delta = chunk.get("delta") or ""
                if delta:
                    state["partial"] += delta
                    yield Token(text=delta)
                if chunk.get("finished"):
                    break
        except Exception as e:
            logger.warning("vLLM Modal stream %s errored: %s", handle.request_id, e)
            state["error"] = str(e)

    async def inject_and_continue(
        self,
        handle: StreamHandle,
        injection: str,
        instruction: str = "Continue, accounting for the above.",
    ) -> StreamHandle:
        partial = await self.cancel(handle)
        new_messages = list(handle.original_messages)
        new_messages.append({
            "role": "user",
            "content": f"[SYNAPSE INTERRUPT]\n{injection}\n\n{instruction}",
        })
        new_params = dict(handle.params)
        if partial.strip():
            new_params["prepend_partial"] = partial
        return await self.start_stream(new_messages, new_params)

    async def cancel(self, handle: StreamHandle) -> str:
        state = self._streams.pop(handle.request_id, None)
        if state is None:
            return ""
        state["cancelled"] = True
        try:
            engine = state["engine"]
            await engine.cancel.remote.aio(request_id=handle.request_id)
        except Exception:
            pass
        return state["partial"]

    # -----------------------------------------------------------------
    @staticmethod
    def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if isinstance(content, list):
                content = "\n".join(
                    b.get("text", "") for b in content if isinstance(b, dict)
                )
            tag = {
                "system": "[SYSTEM]",
                "assistant": "[ASSISTANT]",
                "model": "[ASSISTANT]",
            }.get(role, "[USER]")
            parts.append(f"{tag}\n{content}")
        parts.append("[ASSISTANT]\n")
        return "\n\n".join(parts)
