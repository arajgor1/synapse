"""Ollama local-API adapter.

Talks to a locally-running Ollama server (default http://localhost:11434).
Ollama exposes a `context` array of tokens on each generate response, which
can be passed back to resume a conversation efficiently — that's the core
of the local-API tier mid-stream-injection mechanism.

For Synapse v1, "mid-stream injection" on Ollama is implemented as a
graceful sequence:
  1. Cancel the in-flight HTTP stream (drops connection).
  2. Capture the partial output text from the bytes received so far.
  3. Start a new generate request with prompt = signal + continuation
     instruction, and `context` = last-seen context tokens (so the model
     resumes its KV state without re-processing history).

This is faster than hosted-tier cached-restart because the model never
left the Ollama process — only the HTTP transport reset.
"""

from __future__ import annotations

import json
import logging
import os
import time
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


class OllamaAdapter:
    """Local-API tier adapter for Ollama.

    Args:
        model: Ollama model tag (e.g. "llama3.2:3b", "qwen2.5:7b").
        base_url: Ollama server URL. Default is http://localhost:11434.
        max_tokens: Default num_predict per call.
    """

    def __init__(
        self,
        model: str = "llama3.2:3b",
        base_url: Optional[str] = None,
        max_tokens: int = 512,
    ) -> None:
        try:
            import httpx  # type: ignore[import-not-found]
        except ImportError as e:
            raise BackendUnavailable(
                "httpx not installed. `pip install httpx`."
            ) from e

        self._httpx = httpx
        self._base_url = (base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self._model = model
        self._max_tokens = max_tokens
        self._streams: dict[str, dict[str, Any]] = {}

        self.capabilities = BackendCapabilities(
            backend_id="ollama",
            tier="local_api",
            supports_midstream_inject=True,
            supports_partial_preservation=True,
            is_reasoning_model=False,
            prompt_cache_available=False,  # Ollama context tokens act as cache
            avg_overhead_per_signal=1.08,
            multi_tenant_isolation="process",
            model_id=model,
        )

    # -----------------------------------------------------------------
    async def health_check(self) -> bool:
        """Verify Ollama is reachable and the model is available."""
        async with self._httpx.AsyncClient(timeout=3.0) as client:
            try:
                resp = await client.get(f"{self._base_url}/api/tags")
                resp.raise_for_status()
                tags = resp.json().get("models", [])
                names = {m.get("name", "") for m in tags}
                if self._model not in names:
                    # Ollama lets you list partial matches; allow if base name matches
                    base = self._model.split(":")[0]
                    if not any(n.startswith(base) for n in names):
                        logger.warning(
                            "Ollama model %s not found locally. Available: %s. "
                            "Run: `ollama pull %s`",
                            self._model, sorted(names), self._model,
                        )
                        return False
                return True
            except Exception as e:
                logger.warning("Ollama health check failed: %s", e)
                return False

    # -----------------------------------------------------------------
    async def start_stream(
        self, messages: list[dict[str, Any]], params: dict[str, Any]
    ) -> StreamHandle:
        rid = uuid.uuid4().hex
        prompt = self._messages_to_prompt(messages)

        body = {
            "model": self._model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "num_predict": params.get("max_tokens", self._max_tokens),
                "temperature": params.get("temperature", 0.7),
            },
        }
        # If caller passed a previous-session context, pass it through.
        if "context" in params and params["context"]:
            body["context"] = params["context"]

        client = self._httpx.AsyncClient(timeout=None)
        response_ctx = client.stream("POST", f"{self._base_url}/api/generate", json=body)
        response = await response_ctx.__aenter__()
        if response.status_code != 200:
            text = await response.aread()
            await response_ctx.__aexit__(None, None, None)
            await client.aclose()
            raise BackendUnavailable(
                f"Ollama generate returned HTTP {response.status_code}: {text[:200]!r}"
            )
        self._streams[rid] = {
            "client": client,
            "response_ctx": response_ctx,
            "response": response,
            "partial": "",
            "context": None,  # Filled in when stream completes naturally
            "started_at": time.time(),
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
        response = state["response"]
        try:
            async for line in response.aiter_lines():
                if state["cancelled"]:
                    break
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Ollama: bad JSON line: %r", line[:200])
                    continue
                resp_text = obj.get("response", "")
                if resp_text:
                    state["partial"] += resp_text
                    yield Token(text=resp_text)
                if obj.get("done"):
                    state["context"] = obj.get("context")
                    break
        except Exception as e:
            logger.warning("Ollama stream %s errored: %s", handle.request_id, e)
            state["error"] = str(e)

    async def inject_and_continue(
        self,
        handle: StreamHandle,
        injection: str,
        instruction: str = "Continue, accounting for the above.",
    ) -> StreamHandle:
        """Local-API resume: cancel stream, restart with last context tokens.

        If the stream finished naturally, we have a full context array we can
        use. If it was cancelled mid-flight, context may be None — we fall back
        to providing the partial output as plain prompt prefix (slower but
        correct).
        """
        state = self._streams.get(handle.request_id)
        partial = await self.cancel(handle)
        # Build the new prompt
        new_prompt_messages = list(handle.original_messages)
        if partial.strip():
            new_prompt_messages.append({"role": "assistant", "content": partial})
        new_prompt_messages.append({
            "role": "user",
            "content": f"[SYNAPSE INTERRUPT]\n{injection}\n\n{instruction}",
        })

        new_params = dict(handle.params)
        if state and state.get("context"):
            new_params["context"] = state["context"]

        return await self.start_stream(new_prompt_messages, new_params)

    async def cancel(self, handle: StreamHandle) -> str:
        state = self._streams.pop(handle.request_id, None)
        if state is None:
            return ""
        state["cancelled"] = True
        try:
            await state["response_ctx"].__aexit__(None, None, None)
        except Exception:
            pass
        try:
            await state["client"].aclose()
        except Exception:
            pass
        return state["partial"]

    # -----------------------------------------------------------------
    @staticmethod
    def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
        """Flatten role/content messages into a single prompt string.

        Ollama's /api/generate uses raw prompts (vs /api/chat which has roles).
        We use /api/generate for simpler streaming + context-token resume.
        """
        parts: list[str] = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if isinstance(content, list):
                content = "\n".join(
                    b.get("text", "") for b in content if isinstance(b, dict)
                )
            tag = {"system": "[SYSTEM]", "assistant": "[ASSISTANT]", "model": "[ASSISTANT]"}.get(
                role, "[USER]"
            )
            parts.append(f"{tag}\n{content}")
        parts.append("[ASSISTANT]\n")
        return "\n\n".join(parts)
