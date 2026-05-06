"""Gemini hosted adapter — google-genai SDK.

Same cached-restart pattern as Anthropic, but Gemini's prompt-cache support
varies by SDK version. Adapter probes capabilities at instantiation and
reports honestly.

Env: GOOGLE_API_KEY (or GEMINI_API_KEY).
"""

from __future__ import annotations

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


# Per-1M-token pricing (Gemini paid tier, mid-2026).
_PRICING = {
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.5-pro":   {"input": 1.25,  "output": 5.00},
    "gemini-flash-latest": {"input": 0.075, "output": 0.30},
    "gemini-pro-latest":   {"input": 1.25,  "output": 5.00},
}


class GeminiAdapter:
    """Hosted-tier adapter for Google Gemini.

    Uses the google-genai SDK. With GOOGLE_API_KEY set and a free-tier
    project, this is effectively free for development testing.
    """

    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        api_key: Optional[str] = None,
        max_tokens: int = 1024,
        use_vertex: Optional[bool] = None,
        project: Optional[str] = None,
        location: str = "us-central1",
    ) -> None:
        """Two auth modes:
        - **API key**: pass api_key=... or set GOOGLE_API_KEY/GEMINI_API_KEY env.
        - **Vertex AI**: set use_vertex=True + project=... (or env SYNAPSE_GCP_PROJECT).
          Requires GOOGLE_APPLICATION_CREDENTIALS pointing at a service account JSON,
          or an ADC session via `gcloud auth application-default login`.

        Auto-detect: if use_vertex is None, prefer Vertex when GOOGLE_APPLICATION_CREDENTIALS
        is set AND no API key is available; otherwise fall back to API key.
        """
        try:
            from google import genai  # type: ignore[import-not-found]
        except ImportError as e:
            raise BackendUnavailable(
                "google-genai package not installed. `pip install google-genai`."
            ) from e

        # Resolve auth mode
        env_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        adc_set = bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
        if use_vertex is None:
            use_vertex = adc_set and not (api_key or env_key)

        if use_vertex:
            project = project or os.environ.get("SYNAPSE_GCP_PROJECT")
            if not project:
                raise BackendUnavailable(
                    "Vertex AI mode needs a GCP project. Pass project=... or set SYNAPSE_GCP_PROJECT."
                )
            self._client = genai.Client(vertexai=True, project=project, location=location)
            self._auth_mode = f"vertex:{project}@{location}"
        else:
            key = api_key or env_key
            if not key:
                raise BackendUnavailable(
                    "GOOGLE_API_KEY not set, and no Vertex AI ADC available."
                )
            self._client = genai.Client(api_key=key)
            self._auth_mode = "api_key"

        self._model = model
        self._max_tokens = max_tokens
        self._streams: dict[str, dict[str, Any]] = {}

        self.capabilities = BackendCapabilities(
            backend_id="gemini",
            tier="hosted",
            supports_midstream_inject=True,
            supports_partial_preservation=True,
            is_reasoning_model=False,
            prompt_cache_available=False,  # Conservative — cache support is uneven
            avg_overhead_per_signal=1.20,   # Higher than Anthropic without cache
            multi_tenant_isolation="process",
            model_id=model,
        )

    async def start_stream(
        self, messages: list[dict[str, Any]], params: dict[str, Any]
    ) -> StreamHandle:
        rid = uuid.uuid4().hex
        contents, system_instruction = self._prepare_messages(messages)

        # Gemini SDK's streaming: client.aio.models.generate_content_stream
        config: dict[str, Any] = {
            "max_output_tokens": params.get("max_tokens", self._max_tokens),
        }
        if system_instruction:
            config["system_instruction"] = system_instruction

        # The method is a coroutine that returns an async iterator. await first.
        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=self._model,
                contents=contents,
                config=config,
            )
        except Exception as e:
            raise BackendUnavailable(
                f"Gemini start_stream failed (auth_mode={self._auth_mode}): {e}"
            ) from e
        self._streams[rid] = {
            "stream": stream,
            "partial": "",
            "started_at": time.time(),
            "params": params,
            "messages": messages,
            "system": system_instruction,
            "cancelled": False,
        }
        return StreamHandle(
            request_id=rid,
            original_messages=list(messages),
            params=dict(params),
            extra={"system": system_instruction},
        )

    def read_tokens(self, handle: StreamHandle) -> AsyncIterator[Token]:
        return self._read_tokens(handle)

    async def _read_tokens(self, handle: StreamHandle) -> AsyncIterator[Token]:
        state = self._streams.get(handle.request_id)
        if state is None:
            raise RuntimeError(f"Unknown request: {handle.request_id}")
        stream = state["stream"]
        had_any_text = False
        try:
            async for chunk in stream:
                if state["cancelled"]:
                    break
                # google-genai chunks expose .text directly
                text = getattr(chunk, "text", None)
                if text:
                    had_any_text = True
                    state["partial"] += text
                    yield Token(text=text)
        except Exception as e:
            # Surface upstream errors at WARNING — silent swallow makes adapter
            # bugs look like LLM weirdness.
            logger.warning("Gemini stream %s errored: %s", handle.request_id, e)
            state["error"] = str(e)
        if not had_any_text and not state.get("cancelled"):
            logger.warning(
                "Gemini stream %s produced no text. Auth mode=%s. "
                "Check GOOGLE_API_KEY / Vertex AI quota.",
                handle.request_id, self._auth_mode,
            )

    async def inject_and_continue(
        self,
        handle: StreamHandle,
        injection: str,
        instruction: str = "Continue, accounting for the above.",
    ) -> StreamHandle:
        partial = await self.cancel(handle)
        new_messages = list(handle.original_messages)
        if partial.strip():
            new_messages.append({"role": "model", "content": partial})
        new_messages.append({
            "role": "user",
            "content": f"[SYNAPSE INTERRUPT]\n{injection}\n\n{instruction}",
        })
        return await self.start_stream(new_messages, handle.params)

    async def cancel(self, handle: StreamHandle) -> str:
        state = self._streams.pop(handle.request_id, None)
        if state is None:
            return ""
        state["cancelled"] = True
        return state["partial"]

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------
    def _prepare_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], Optional[str]]:
        """Gemini takes 'contents' (list) and optional 'system_instruction'.

        We accept the same input shape as Anthropic (role/content dicts),
        translate the system role into system_instruction, and convert
        'assistant' role to Gemini's 'model'.
        """
        system_instruction: Optional[str] = None
        contents: list[dict[str, Any]] = []
        for m in messages:
            role = m.get("role", "user")
            if role == "system":
                if system_instruction is None:
                    sys_content = m.get("content")
                    if isinstance(sys_content, list):
                        # Concatenate text blocks
                        sys_text_parts = [
                            b.get("text", "") for b in sys_content if isinstance(b, dict)
                        ]
                        system_instruction = "\n".join(sys_text_parts)
                    else:
                        system_instruction = str(sys_content) if sys_content else None
                continue
            gemini_role = "model" if role == "assistant" else "user"
            content = m.get("content")
            if isinstance(content, list):
                # Concatenate text blocks
                text_parts = [b.get("text", "") for b in content if isinstance(b, dict)]
                text = "\n".join(text_parts)
            else:
                text = str(content) if content else ""
            contents.append({"role": gemini_role, "parts": [{"text": text}]})
        return contents, system_instruction

    @staticmethod
    def estimate_cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
        p = _PRICING.get(model) or _PRICING.get("gemini-2.5-flash", {"input": 0.075, "output": 0.30})
        return tokens_in * p["input"] / 1_000_000 + tokens_out * p["output"] / 1_000_000
