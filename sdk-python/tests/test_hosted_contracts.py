"""Contract tests for hosted adapters — feed them documented SDK event/chunk
shapes and verify they extract the right text. No real API calls.

This is the documentation-driven equivalent of an integration test: we replay
the exact event shapes the official SDKs emit (per their docs) and check that
the adapter's read_tokens() yields the expected Token text.

Sources:
- Anthropic streaming docs: https://docs.anthropic.com/en/docs/build-with-claude/streaming
  Specifically the message_stream event sequence with content_block_delta and
  the {"type": "text_delta", "text": "..."} delta shape.
- OpenAI Chat Completions streaming: chunks with choices[0].delta.content
  (None for first chunk that only has role; None for last chunk with finish_reason).
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, AsyncIterator

import pytest


# -----------------------------------------------------------------------------
# Fake event objects mirroring the real SDK shapes
# -----------------------------------------------------------------------------
@dataclass
class FakeAnthropicTextDelta:
    type: str = "text_delta"
    text: str = ""


@dataclass
class FakeAnthropicInputJsonDelta:
    """Tool-use streaming delta — adapter should ignore."""
    type: str = "input_json_delta"
    partial_json: str = ""


@dataclass
class FakeAnthropicThinkingDelta:
    """Extended-thinking delta — adapter should ignore for v1."""
    type: str = "thinking_delta"
    thinking: str = ""


@dataclass
class FakeAnthropicEvent:
    type: str
    delta: Any = None


class FakeAnthropicStream:
    """Mimics anthropic.lib.streaming._messages.MessageStreamManager.__aenter__()
    return value: an async-iterable yielding stream events."""

    def __init__(self, events: list[FakeAnthropicEvent]):
        self._events = events

    def __aiter__(self):
        async def gen():
            for e in self._events:
                yield e
        return gen()


class FakeAnthropicStreamCtx:
    """Mimics the AsyncContextManager returned by client.messages.stream(...)."""

    def __init__(self, events: list[FakeAnthropicEvent]):
        self._events = events
        self._exited = False

    async def __aenter__(self):
        return FakeAnthropicStream(self._events)

    async def __aexit__(self, exc_type, exc, tb):
        self._exited = True
        return False


class FakeAnthropicMessages:
    def __init__(self, events: list[FakeAnthropicEvent]):
        self._events = events

    def stream(self, **kwargs):
        return FakeAnthropicStreamCtx(self._events)


# -----------------------------------------------------------------------------
# Fake OpenAI chunk shape
# -----------------------------------------------------------------------------
@dataclass
class FakeOpenAIDelta:
    content: str | None = None
    role: str | None = None


@dataclass
class FakeOpenAIChoice:
    delta: FakeOpenAIDelta
    index: int = 0
    finish_reason: str | None = None


@dataclass
class FakeOpenAIChunk:
    choices: list[FakeOpenAIChoice]
    id: str = "chatcmpl-fake"
    object: str = "chat.completion.chunk"


class FakeOpenAIStream:
    """Async iterable matching the AsyncStream protocol from openai-python."""

    def __init__(self, chunks: list[FakeOpenAIChunk]):
        self._chunks = chunks
        self.closed = False

    def __aiter__(self):
        async def gen():
            for c in self._chunks:
                yield c
        return gen()

    async def close(self):
        self.closed = True


# =============================================================================
# Anthropic adapter contract tests
# =============================================================================
class TestAnthropicAdapterAgainstSDKContract:
    """Verify the adapter handles documented Anthropic stream event shapes."""

    @pytest.fixture
    def adapter(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
        from synapse.adapters.hosted import AnthropicAdapter
        adapter = AnthropicAdapter(model="claude-haiku-4-5-20251001")
        return adapter

    @pytest.mark.asyncio
    async def test_pure_text_stream_yields_all_tokens(self, adapter, monkeypatch):
        """Documented happy path: a sequence of content_block_delta events with
        text_delta payloads. Adapter should yield each as a Token."""
        events = [
            FakeAnthropicEvent("message_start"),
            FakeAnthropicEvent("content_block_start"),
            FakeAnthropicEvent("content_block_delta", FakeAnthropicTextDelta(text="Hello")),
            FakeAnthropicEvent("content_block_delta", FakeAnthropicTextDelta(text=" world")),
            FakeAnthropicEvent("content_block_delta", FakeAnthropicTextDelta(text="!")),
            FakeAnthropicEvent("content_block_stop"),
            FakeAnthropicEvent("message_stop"),
        ]
        adapter._client.messages = FakeAnthropicMessages(events)
        handle = await adapter.start_stream(
            messages=[{"role": "user", "content": "hi"}], params={}
        )
        tokens = [t.text async for t in adapter.read_tokens(handle)]
        assert tokens == ["Hello", " world", "!"]

    @pytest.mark.asyncio
    async def test_input_json_delta_ignored(self, adapter):
        """Tool-use streaming sends input_json_delta. Adapter should skip
        these (they aren't text). This is the bug found in code review."""
        events = [
            FakeAnthropicEvent("content_block_delta", FakeAnthropicTextDelta(text="Plan:")),
            # Tool-use args streaming — must NOT be yielded as text
            FakeAnthropicEvent("content_block_delta",
                               FakeAnthropicInputJsonDelta(partial_json='{"x":1}')),
            FakeAnthropicEvent("content_block_delta", FakeAnthropicTextDelta(text=" done.")),
        ]
        adapter._client.messages = FakeAnthropicMessages(events)
        handle = await adapter.start_stream(
            messages=[{"role": "user", "content": "plan it"}], params={}
        )
        tokens = [t.text async for t in adapter.read_tokens(handle)]
        # Only the two text_delta events should yield Tokens
        assert tokens == ["Plan:", " done."]

    @pytest.mark.asyncio
    async def test_thinking_delta_ignored(self, adapter):
        """Extended-thinking models emit thinking_delta. v1 adapter ignores."""
        events = [
            FakeAnthropicEvent("content_block_delta",
                               FakeAnthropicThinkingDelta(thinking="reasoning...")),
            FakeAnthropicEvent("content_block_delta", FakeAnthropicTextDelta(text="The answer.")),
        ]
        adapter._client.messages = FakeAnthropicMessages(events)
        handle = await adapter.start_stream(
            messages=[{"role": "user", "content": "?"}], params={}
        )
        tokens = [t.text async for t in adapter.read_tokens(handle)]
        assert tokens == ["The answer."]

    @pytest.mark.asyncio
    async def test_partial_text_preserved_on_cancel(self, adapter):
        events = [
            FakeAnthropicEvent("content_block_delta", FakeAnthropicTextDelta(text="part1")),
            FakeAnthropicEvent("content_block_delta", FakeAnthropicTextDelta(text=" part2")),
        ]
        adapter._client.messages = FakeAnthropicMessages(events)
        handle = await adapter.start_stream(
            messages=[{"role": "user", "content": "x"}], params={}
        )
        # Read first token then cancel
        it = adapter.read_tokens(handle)
        first = await it.__anext__()
        assert first.text == "part1"
        partial = await adapter.cancel(handle)
        assert "part1" in partial

    @pytest.mark.asyncio
    async def test_inject_and_continue_constructs_correct_messages(self, adapter):
        """Verify the cached-restart message structure matches the documented
        prompt-caching format."""
        events = [
            FakeAnthropicEvent("content_block_delta", FakeAnthropicTextDelta(text="ack")),
        ]
        adapter._client.messages = FakeAnthropicMessages(events)

        # First call to populate handle.original_messages
        original_msgs = [
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": "Plan the refactor."},
        ]
        handle = await adapter.start_stream(messages=original_msgs, params={})
        partial = "I'll first audit the imports"
        adapter._streams[handle.request_id]["partial"] = partial

        # Now do inject_and_continue
        new_handle = await adapter.inject_and_continue(
            handle, injection="Agent B claims this scope", instruction="Pivot."
        )

        # The new handle's messages should:
        # - End with a [SYNAPSE INTERRUPT] user message
        # - Have the assistant partial output before that
        # - Have cache_control on the last message of the original prefix
        # Note: we verify by inspecting the kwargs dict the fake client receives
        # ... but since we just track via _streams, check the new stream state
        new_state = adapter._streams[new_handle.request_id]
        msgs = new_state["messages"]
        assert msgs[-1]["role"] == "user"
        assert "[SYNAPSE INTERRUPT]" in msgs[-1]["content"]
        assert "Agent B claims this scope" in msgs[-1]["content"]
        # Assistant partial appears before the interrupt
        assert any(m.get("role") == "assistant" and m.get("content") == partial for m in msgs)


# =============================================================================
# OpenAI adapter contract tests
# =============================================================================
class TestOpenAIAdapterAgainstSDKContract:
    @pytest.fixture
    def adapter(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
        from synapse.adapters.hosted import OpenAIAdapter
        adapter = OpenAIAdapter(model="gpt-4o-mini")
        return adapter

    @pytest.mark.asyncio
    async def test_extracts_text_from_documented_chunk_shape(self, adapter):
        """Standard openai-python chunk shape:
        chunk.choices[0].delta.content -> string token (or None)."""
        chunks = [
            # First chunk often has only role, no content
            FakeOpenAIChunk([FakeOpenAIChoice(FakeOpenAIDelta(role="assistant"))]),
            FakeOpenAIChunk([FakeOpenAIChoice(FakeOpenAIDelta(content="Hello"))]),
            FakeOpenAIChunk([FakeOpenAIChoice(FakeOpenAIDelta(content=" world"))]),
            # Last chunk has finish_reason and empty/None content
            FakeOpenAIChunk([FakeOpenAIChoice(FakeOpenAIDelta(content=None),
                                              finish_reason="stop")]),
        ]
        fake_stream = FakeOpenAIStream(chunks)

        # Patch the create method to return our fake stream
        async def fake_create(**kwargs):
            return fake_stream
        adapter._client.chat.completions.create = fake_create

        handle = await adapter.start_stream(
            messages=[{"role": "user", "content": "hi"}], params={}
        )
        tokens = [t.text async for t in adapter.read_tokens(handle)]
        # Role-only and finish_reason chunks should NOT yield tokens
        assert tokens == ["Hello", " world"]

    @pytest.mark.asyncio
    async def test_empty_choices_chunk_skipped(self, adapter):
        """Some chunks can have an empty choices list (rare but documented)."""
        chunks = [
            FakeOpenAIChunk(choices=[]),
            FakeOpenAIChunk([FakeOpenAIChoice(FakeOpenAIDelta(content="ok"))]),
        ]
        fake_stream = FakeOpenAIStream(chunks)

        async def fake_create(**kwargs):
            return fake_stream
        adapter._client.chat.completions.create = fake_create

        handle = await adapter.start_stream(
            messages=[{"role": "user", "content": "hi"}], params={}
        )
        tokens = [t.text async for t in adapter.read_tokens(handle)]
        assert tokens == ["ok"]

    @pytest.mark.asyncio
    async def test_cancel_calls_close_on_stream(self, adapter):
        chunks = [FakeOpenAIChunk([FakeOpenAIChoice(FakeOpenAIDelta(content="x"))])]
        fake_stream = FakeOpenAIStream(chunks)

        async def fake_create(**kwargs):
            return fake_stream
        adapter._client.chat.completions.create = fake_create

        handle = await adapter.start_stream(
            messages=[{"role": "user", "content": "hi"}], params={}
        )
        await adapter.cancel(handle)
        assert fake_stream.closed is True

    @pytest.mark.asyncio
    async def test_partial_preserved_on_cancel(self, adapter):
        chunks = [
            FakeOpenAIChunk([FakeOpenAIChoice(FakeOpenAIDelta(content="part1"))]),
            FakeOpenAIChunk([FakeOpenAIChoice(FakeOpenAIDelta(content=" part2"))]),
        ]
        fake_stream = FakeOpenAIStream(chunks)

        async def fake_create(**kwargs):
            return fake_stream
        adapter._client.chat.completions.create = fake_create

        handle = await adapter.start_stream(
            messages=[{"role": "user", "content": "hi"}], params={}
        )
        it = adapter.read_tokens(handle)
        first = await it.__anext__()
        assert first.text == "part1"
        partial = await adapter.cancel(handle)
        assert "part1" in partial

    @pytest.mark.asyncio
    async def test_inject_and_continue_appends_synapse_interrupt(self, adapter):
        chunks = [FakeOpenAIChunk([FakeOpenAIChoice(FakeOpenAIDelta(content="ok"))])]
        fake_stream = FakeOpenAIStream(chunks)

        async def fake_create(**kwargs):
            return FakeOpenAIStream(list(chunks))
        adapter._client.chat.completions.create = fake_create

        original_msgs = [{"role": "user", "content": "Plan it."}]
        handle = await adapter.start_stream(messages=original_msgs, params={})
        adapter._streams[handle.request_id]["partial"] = "Step 1: audit"

        new_handle = await adapter.inject_and_continue(
            handle, injection="Conflict detected", instruction="Pause and reconsider."
        )
        new_msgs = adapter._streams[new_handle.request_id]["messages"]
        # Final user message has the SYNAPSE INTERRUPT marker
        assert "[SYNAPSE INTERRUPT]" in new_msgs[-1]["content"]
        # Assistant partial preserved
        assert any(m.get("role") == "assistant" for m in new_msgs)
