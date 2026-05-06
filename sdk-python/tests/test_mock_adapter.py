"""Tests for the mock inference adapter — the Phase 1 reference adapter."""

from __future__ import annotations

import asyncio

import pytest

from synapse.adapters import MockAdapter


pytestmark = pytest.mark.asyncio


async def _collect(stream) -> str:
    out = []
    async for tok in stream:
        out.append(tok.text)
    return "".join(out).strip()


async def test_basic_streaming() -> None:
    adapter = MockAdapter(scripted_response="hello world", delay_per_token_ms=0)
    handle = await adapter.start_stream(messages=[], params={})
    text = await _collect(adapter.read_tokens(handle))
    assert text == "hello world"


async def test_inject_and_continue_resumes_after_partial() -> None:
    adapter = MockAdapter(
        scripted_response="i am about to make a mistake on auth",
        delay_per_token_ms=2,
    )
    handle = await adapter.start_stream(messages=[], params={})

    # Read a few tokens then trigger an injection mid-stream.
    iter_ = adapter.read_tokens(handle)
    collected = []
    for _ in range(3):
        tok = await iter_.__anext__()
        collected.append(tok.text)

    # Now inject a signal — adapter cancels the original stream and returns a new handle.
    new_handle = await adapter.inject_and_continue(
        handle,
        injection="Agent A claimed auth.middleware",
        instruction="Pivot to a different scope.",
    )

    new_text = await _collect(adapter.read_tokens(new_handle))
    # The continuation should reference both the partial and the injection.
    assert "acknowledged signal" in new_text
    assert "Agent A claimed auth.middleware" in new_text


async def test_capabilities_advertised() -> None:
    adapter = MockAdapter()
    caps = adapter.capabilities
    assert caps.backend_id == "mock"
    assert caps.tier == "native"
    assert caps.supports_midstream_inject is True
    assert caps.is_reasoning_model is False


async def test_cancel_returns_partial() -> None:
    adapter = MockAdapter(scripted_response="one two three four", delay_per_token_ms=10)
    handle = await adapter.start_stream(messages=[], params={})

    iter_ = adapter.read_tokens(handle)
    await iter_.__anext__()  # consume one token
    partial = await adapter.cancel(handle)
    # Mock state captures emitted tokens
    assert "one" in partial
