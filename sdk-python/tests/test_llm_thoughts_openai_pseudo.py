"""v0.2.8 fix: wrap_openai_for_thoughts must capture message.content as
PSEUDO_THOUGHT when no native reasoning field is present (gpt-4o-mini, gpt-4o,
gpt-4, etc.). Without this fallback, the OpenAI route emitted 0/10 THOUGHTs
in v32 while the Anthropic route emitted 9/9.
"""
from __future__ import annotations

import asyncio
import os
import sys
import types

import pytest

# Make synapse importable when tests run from the sdk-python dir.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _FakeMsg:
    def __init__(self, content, reasoning=None):
        self.content = content
        if reasoning is not None:
            self.reasoning = reasoning


class _FakeChoice:
    def __init__(self, content, reasoning=None):
        self.message = _FakeMsg(content, reasoning)


class _FakeResp:
    def __init__(self, content, reasoning=None):
        self.choices = [_FakeChoice(content, reasoning)]


def _make_fake_client(content, reasoning=None):
    class FakeCompletions:
        async def create(self, **kw):
            return _FakeResp(content, reasoning)
    chat = types.SimpleNamespace(completions=FakeCompletions())
    return types.SimpleNamespace(chat=chat)


@pytest.mark.asyncio
async def test_openai_pseudo_thought_captured_for_chat_content():
    """gpt-4o-mini path: no `reasoning` field, but message.content is the
    model's explicit prose. Must emit a PSEUDO_THOUGHT envelope.
    """
    from synapse import llm_thoughts as lt

    captured: list[dict] = []

    async def fake_emit(*, session_id, agent_id, parent_intention_id, block_info):
        captured.append({"session": session_id, "agent": agent_id,
                         "block": block_info})

    # Monkey-patch the emit fn so we don't need a real bus.
    real_emit = lt._emit_thought
    lt._emit_thought = fake_emit
    try:
        client = _make_fake_client(
            content="I will write a complete Flask app: from flask import Flask...",
            reasoning=None,
        )
        wrapped = lt.wrap_openai_for_thoughts(
            client, session_id="t", agent_id="agentX",
        )
        await wrapped.chat.completions.create(model="gpt-4o-mini", messages=[])
        # Allow background asyncio.create_task to run
        await asyncio.sleep(0.1)
    finally:
        lt._emit_thought = real_emit

    assert len(captured) == 1, f"expected 1 captured thought, got {captured}"
    assert captured[0]["block"]["kind"] == "pseudo_thought"
    assert "flask" in captured[0]["block"]["text"].lower()
    assert captured[0]["session"] == "t"
    assert captured[0]["agent"] == "agentX"


@pytest.mark.asyncio
async def test_openai_reasoning_field_still_wins_when_present():
    """o-series models have `reasoning`. When both reasoning AND content are
    present, capture the reasoning text with kind='reasoning' (not content)."""
    from synapse import llm_thoughts as lt

    captured: list[dict] = []

    async def fake_emit(*, session_id, agent_id, parent_intention_id, block_info):
        captured.append(block_info)

    real_emit = lt._emit_thought
    lt._emit_thought = fake_emit
    try:
        client = _make_fake_client(
            content="The answer is 42.",
            reasoning="Step 1: parse the question. Step 2: compute 6*7.",
        )
        wrapped = lt.wrap_openai_for_thoughts(client, session_id="t",
                                              agent_id="o1_agent")
        await wrapped.chat.completions.create(model="o1-mini", messages=[])
        await asyncio.sleep(0.1)
    finally:
        lt._emit_thought = real_emit

    assert len(captured) == 1
    assert captured[0]["kind"] == "reasoning"  # reasoning beats content
    assert "Step 1" in captured[0]["text"]


@pytest.mark.asyncio
async def test_openai_empty_content_skipped():
    """If both reasoning AND content are empty/missing, emit nothing.
    Audit trail stays clean — no false positives."""
    from synapse import llm_thoughts as lt

    captured: list[dict] = []

    async def fake_emit(*, session_id, agent_id, parent_intention_id, block_info):
        captured.append(block_info)

    real_emit = lt._emit_thought
    lt._emit_thought = fake_emit
    try:
        client = _make_fake_client(content="", reasoning=None)
        wrapped = lt.wrap_openai_for_thoughts(client, session_id="t",
                                              agent_id="empty")
        await wrapped.chat.completions.create(model="gpt-4o", messages=[])
        await asyncio.sleep(0.1)
    finally:
        lt._emit_thought = real_emit

    assert len(captured) == 0
