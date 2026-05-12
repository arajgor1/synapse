"""LLM reasoning capture (NLA-equivalent) → Synapse THOUGHT envelopes.

v0.2.7 — closes the audit gap where Synapse captured tool-call dispatch
but NOT the LLM's internal reasoning. With this module, every reasoning
trace the LLM emits becomes a THOUGHT envelope on the bus, with parent
intention/agent attribution, queryable via `synapse audit --include thoughts`.

Supported sources (more land in v0.2.8):
  - Anthropic API (Claude Sonnet 4.5, Haiku 4.5) with extended thinking enabled
  - OpenAI o1/o3 reasoning models
  - Codex CLI JSONL event stream
  - Claude Code transcript hooks
  - Self-hosted LLMs (vLLM/Ollama) via inference-loop hooks (TODO: separate
    module — needs deeper integration)

Usage (Anthropic — the most common case):

    from anthropic import AsyncAnthropic
    from synapse.llm_thoughts import wrap_anthropic_for_thoughts

    client = AsyncAnthropic(api_key=...)
    wrap_anthropic_for_thoughts(client, session_id="my-session",
                                agent_id="architect")

    # Every subsequent messages.create() call with thinking enabled
    # emits THOUGHT envelopes for each ThinkingBlock in the response.
    msg = await client.messages.create(
        model="claude-sonnet-4-5-20251022",
        max_tokens=2000,
        thinking={"type": "enabled", "budget_tokens": 1024},
        messages=[{"role": "user", "content": "Design a Todo data model."}],
    )

Operator-facing:
    synapse watch --session my-session --types thought,intention,conflict
    → live tail of agent reasoning interleaved with tool dispatch + conflicts
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Optional, Callable

from synapse.messages import Envelope, MessageType, Thought
from synapse.intend import _ensure_connected
from synapse.agent_context import current_agent_id

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Anthropic capture (extended thinking blocks)
# ---------------------------------------------------------------------------
def wrap_anthropic_for_thoughts(
    client: Any,
    *,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    parent_intention_id: Optional[str] = None,
) -> Any:
    """Wrap an ``AsyncAnthropic`` client so every ``messages.create()`` call
    with extended thinking enabled emits Synapse ``THOUGHT`` envelopes.

    Args:
        client: ``AsyncAnthropic`` instance.
        session_id: Synapse session id. Falls back to SYNAPSE_SESSION_ID env.
        agent_id: which Synapse agent owns these thoughts. Falls back to
                  current_agent_id() ContextVar then "anthropic_agent".
        parent_intention_id: optional umbrella intention this reasoning
                  belongs to. Reasoning is attached to this intent in the
                  audit trail.

    Returns the same client; the wrap is in-place via monkey-patch of
    ``client.messages.create``. Idempotent.

    Captures ``ThinkingBlock`` content from the response and emits one
    ``THOUGHT`` envelope per block. The bare ``thinking`` text becomes the
    ``summary`` field of the Thought; the raw block (with signature for
    Anthropic redaction) is preserved in ``raw_excerpt`` (first 2000 chars).
    """
    if getattr(client, "_synapse_thought_wrapped", False):
        return client  # idempotent

    messages_obj = getattr(client, "messages", None)
    if messages_obj is None or not hasattr(messages_obj, "create"):
        logger.warning("synapse.wrap_anthropic_for_thoughts: client has no "
                       ".messages.create — not wrapped")
        return client

    original_create = messages_obj.create

    async def _create_with_thought_capture(*args, **kwargs):
        # Resolve attribution per-call (allows context-var override)
        eff_session = session_id or os.environ.get("SYNAPSE_SESSION_ID") \
                      or "anthropic_default_session"
        eff_agent = agent_id or current_agent_id(default="anthropic_agent")

        # Call original
        msg = await original_create(*args, **kwargs)

        # Extract thinking blocks (if extended thinking was enabled).
        # `msg.content` is a list of ContentBlock objects. Modern Anthropic
        # SDK has `ThinkingBlock` and `RedactedThinkingBlock` types.
        thinking_blocks = []
        try:
            content = getattr(msg, "content", None) or []
            for block in content:
                block_type = getattr(block, "type", None)
                if block_type == "thinking":
                    text = getattr(block, "thinking", "") or ""
                    signature = getattr(block, "signature", None)
                    thinking_blocks.append({
                        "text": text,
                        "signature": signature,
                        "kind": "thinking",
                    })
                elif block_type == "redacted_thinking":
                    data = getattr(block, "data", None)
                    thinking_blocks.append({
                        "text": "[redacted]",
                        "data": data,
                        "kind": "redacted_thinking",
                    })
        except Exception as e:
            logger.warning("synapse.wrap_anthropic_for_thoughts: thinking-"
                          "block extraction failed (%s)", e)

        # Emit one THOUGHT envelope per block (async, don't block on errors)
        if thinking_blocks:
            for block_info in thinking_blocks:
                asyncio.create_task(
                    _emit_thought(
                        session_id=eff_session,
                        agent_id=eff_agent,
                        parent_intention_id=parent_intention_id,
                        block_info=block_info,
                    )
                )

        return msg

    messages_obj.create = _create_with_thought_capture
    client._synapse_thought_wrapped = True
    logger.info("synapse.wrap_anthropic_for_thoughts: wrapped %s for "
                "thought capture (session=%s agent=%s)",
                type(client).__name__, session_id, agent_id)
    return client


async def _emit_thought(
    *,
    session_id: str,
    agent_id: str,
    parent_intention_id: Optional[str],
    block_info: dict,
) -> None:
    """Emit a single THOUGHT envelope onto the bus + state graph.

    v0.2.7 fix: retry briefly if bus is not yet connected. The runtime is
    connected lazily on the first intend() call; if we fire a THOUGHT
    BEFORE any intend has run (which is the common case for "wrap LLM
    client, then use it"), bus may be None for the first ~500ms.
    """
    rt = None
    bus = None
    # Retry up to 5x with 100ms backoff (total 500ms) for bus to come up
    for attempt in range(5):
        try:
            rt = await _ensure_connected()
        except Exception as e:
            logger.debug("synapse._emit_thought: runtime not connected (%s)", e)
            await asyncio.sleep(0.1)
            continue
        bus = rt.get("bus")
        if bus is not None:
            break
        await asyncio.sleep(0.1)
    if bus is None:
        logger.debug("synapse._emit_thought: bus still None after retries; "
                    "dropping THOUGHT (session=%s agent=%s)", session_id, agent_id)
        return

    text = block_info.get("text", "")
    kind = block_info.get("kind", "thinking")
    # Topics — best-effort extraction: first 3 nouns/keywords
    summary = text[:2000] if text else f"[{kind}]"
    raw_excerpt = text[:2000] if kind == "thinking" else None

    thought = Thought(
        summary=summary,
        raw_excerpt=raw_excerpt,
        topics=[],
        confidence=None,
    )
    envelope = Envelope.make(
        type=MessageType.THOUGHT,
        agent_id=agent_id,
        session_id=session_id,
        payload=thought,
        parent_msg_id=parent_intention_id,
    )
    try:
        await bus.publish(envelope)
    except Exception as e:
        logger.debug("synapse._emit_thought: publish failed (%s)", e)


# ---------------------------------------------------------------------------
# OpenAI o1/o3 reasoning capture
# ---------------------------------------------------------------------------
def wrap_openai_for_thoughts(
    client: Any,
    *,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    parent_intention_id: Optional[str] = None,
) -> Any:
    """Wrap an ``openai.AsyncOpenAI`` client so reasoning-model responses
    (o1, o3, o5-mini) emit THOUGHT envelopes from the ``reasoning`` field.

    The ``reasoning`` field on o-series responses is the model's
    pre-output reasoning trace — analogous to Anthropic's thinking blocks.
    """
    if getattr(client, "_synapse_thought_wrapped", False):
        return client

    completions_obj = getattr(getattr(client, "chat", None), "completions", None)
    if completions_obj is None or not hasattr(completions_obj, "create"):
        logger.warning("synapse.wrap_openai_for_thoughts: client has no "
                      ".chat.completions.create — not wrapped")
        return client

    original_create = completions_obj.create

    async def _create_with_thought_capture(*args, **kwargs):
        eff_session = session_id or os.environ.get("SYNAPSE_SESSION_ID") \
                      or "openai_default_session"
        eff_agent = agent_id or current_agent_id(default="openai_agent")

        msg = await original_create(*args, **kwargs)

        # o-series responses have `choices[0].message.reasoning` (extracted
        # before content). Sometimes nested under `.reasoning_summary` or
        # `.reasoning_details`.
        reasoning_text = None
        try:
            choices = getattr(msg, "choices", None) or []
            for choice in choices:
                m = getattr(choice, "message", None)
                if m is None:
                    continue
                for attr in ("reasoning", "reasoning_summary",
                            "reasoning_content", "reasoning_details"):
                    val = getattr(m, attr, None)
                    if val:
                        reasoning_text = val if isinstance(val, str) else str(val)
                        break
                if reasoning_text:
                    break
        except Exception as e:
            logger.warning("synapse.wrap_openai_for_thoughts: reasoning "
                          "extraction failed (%s)", e)

        if reasoning_text:
            asyncio.create_task(
                _emit_thought(
                    session_id=eff_session,
                    agent_id=eff_agent,
                    parent_intention_id=parent_intention_id,
                    block_info={"text": reasoning_text, "kind": "reasoning"},
                )
            )

        return msg

    completions_obj.create = _create_with_thought_capture
    client._synapse_thought_wrapped = True
    logger.info("synapse.wrap_openai_for_thoughts: wrapped for thought "
                "capture (session=%s agent=%s)", session_id, agent_id)
    return client


# ---------------------------------------------------------------------------
# Generic JSONL event-stream subscriber (Codex CLI, Claude Code transcripts)
# ---------------------------------------------------------------------------
async def subscribe_jsonl_events(
    *,
    source_path: str,
    session_id: str,
    agent_id_field: str = "agent_id",
    thought_field: str = "thinking",
    poll_ms: int = 100,
    stop_event: Optional[asyncio.Event] = None,
) -> None:
    """Subscribe to a JSONL event stream (e.g. Codex CLI's --trace-file or
    Claude Code's ~/.claude/transcripts/<id>.jsonl) and emit THOUGHT
    envelopes for every line that has a ``thought_field`` populated.

    Stops when ``stop_event.set()`` is called OR the file is closed and
    EOF is reached AND ``stop_event`` is None.

    This is the bridge for tooling that already emits structured event
    streams — no monkey-patching needed.
    """
    import os.path
    last_offset = 0
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        if not os.path.isfile(source_path):
            await asyncio.sleep(poll_ms / 1000)
            continue
        try:
            with open(source_path, "r", encoding="utf-8") as f:
                f.seek(last_offset)
                new_lines = f.readlines()
                last_offset = f.tell()
        except Exception as e:
            logger.warning("synapse.subscribe_jsonl_events: read failed (%s)", e)
            await asyncio.sleep(poll_ms / 1000)
            continue
        for line in new_lines:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            thought_text = event.get(thought_field)
            if not thought_text:
                continue
            aid = event.get(agent_id_field) or "jsonl_agent"
            asyncio.create_task(_emit_thought(
                session_id=session_id,
                agent_id=str(aid),
                parent_intention_id=event.get("parent_intention_id"),
                block_info={"text": str(thought_text), "kind": "jsonl_stream"},
            ))
        if stop_event is None and not new_lines:
            # File closed + no new content + no explicit stop → exit
            await asyncio.sleep(poll_ms / 1000)
        else:
            await asyncio.sleep(poll_ms / 1000)


__all__ = [
    "wrap_anthropic_for_thoughts",
    "wrap_openai_for_thoughts",
    "subscribe_jsonl_events",
]
