"""LLM-driven belief extraction from tool outputs.

When ``emit_beliefs_from_tool_results=True``, every successful intend()
block runs this extractor on its tool's state_diff. The extractor calls
the user's BYO-LLM (via ``synapse.set_llm``) with a prompt asking it to
identify domain facts the agent now believes.

The extractor is intentionally narrow: it produces 0–3 facts per call,
and only when there's strong textual evidence. Hallucinated beliefs
poison divergence detection, so we err on the side of fewer/no beliefs.

If no LLM is configured, the extractor is a no-op and returns ``[]``.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class FactExtraction:
    """One belief extracted from a tool result."""
    key: str
    value: Any
    confidence: float = 0.85
    evidence: Optional[str] = None  # snippet of the source text


_PROMPT_TEMPLATE = """You are inspecting a tool call result from an AI agent.
Extract domain facts the agent now believes — DO NOT invent facts not present
in the output.

Tool: {tool_name}
Args: {tool_args}
Output: {output}

Return a JSON list of 0 to 3 facts. Each fact must have:
  - key: a stable, kebab-case identifier ({{e.g. "revenue_formula", "primary_key_column", "table_name"}}).
        Use the SAME key two agents would naturally pick for the same fact.
  - value: the literal fact (string, number, list, etc).
  - confidence: 0.0 to 1.0
  - evidence: 1-line snippet from the output that supports the fact

Only emit facts you are CERTAIN are present in the output. If the output is
generic/uninteresting, return []. Output ONLY the JSON list, no other text.

Examples (illustrative — return only what's actually in the output):
  [{{"key": "revenue_formula", "value": "qty * price", "confidence": 0.95, "evidence": "revenue = qty * price"}}]
  [{{"key": "primary_key", "value": "user_id", "confidence": 0.9, "evidence": "PRIMARY KEY (user_id)"}}]
  []
"""


async def extract_beliefs_with_llm(
    *,
    tool_name: str,
    tool_args: dict,
    output: Any,
    llm: Optional[Any] = None,
    max_output_chars: int = 1500,
) -> list[FactExtraction]:
    """Use the configured LLM (or one passed explicitly) to extract beliefs
    from a tool result. Returns ``[]`` if no LLM is configured.
    """
    if llm is None:
        from synapse.llm.config import get_internal_llm
        llm = get_internal_llm()
    if llm is None:
        return []

    text_output = str(output)[:max_output_chars]
    if not text_output.strip():
        return []

    prompt = _PROMPT_TEMPLATE.format(
        tool_name=tool_name,
        tool_args=json.dumps(tool_args, default=str)[:500],
        output=text_output,
    )

    text = await _llm_text(llm, prompt)
    if not text:
        return []

    return _parse_extraction(text)


def _parse_extraction(text: str) -> list[FactExtraction]:
    """Parse LLM output into FactExtraction list. Tolerant of code fences."""
    cleaned = text.strip()
    # Strip markdown code fences if present
    fence = re.match(r"^```(?:json)?\s*(.*)```\s*$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    # Look for first [ and last ] to be tolerant of preamble
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        items = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        logger.debug("belief extractor: LLM returned non-JSON; got: %r", text[:200])
        return []
    out: list[FactExtraction] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if "key" not in it or "value" not in it:
            continue
        try:
            confidence = float(it.get("confidence", 0.85))
        except (TypeError, ValueError):
            confidence = 0.85
        out.append(
            FactExtraction(
                key=str(it["key"]).strip(),
                value=it["value"],
                confidence=max(0.0, min(1.0, confidence)),
                evidence=str(it.get("evidence") or "")[:200] or None,
            )
        )
    return out[:3]  # safety cap


async def _llm_text(llm, prompt: str) -> str:
    """Same multi-path LLM caller as policies.builtin._llm_call_text.

    Tries (in order): bridge .generate() → native Anthropic _client →
    native OpenAI _client. Returns "" on any failure.
    """
    messages = [{"role": "user", "content": prompt}]

    try:
        if hasattr(llm, "generate"):
            text = await llm.generate(messages=messages, max_tokens=300, temperature=0.0)
            if isinstance(text, str) and text.strip():
                return text.strip()
    except Exception as e:
        logger.debug("belief extractor: llm.generate failed (%s)", e)

    client = getattr(llm, "_client", None)
    model = getattr(llm, "_model", None) or "claude-haiku-4-5-20251001"

    # Anthropic
    if client is not None and hasattr(client, "messages"):
        try:
            msg = await client.messages.create(
                model=model, max_tokens=300, messages=messages,
            )
            blocks = msg.content if msg and getattr(msg, "content", None) else []
            text = blocks[0].text if blocks and hasattr(blocks[0], "text") else ""
            if text and text.strip():
                return text.strip()
        except Exception as e:
            logger.debug("belief extractor: anthropic fallback failed (%s)", e)

    # OpenAI-shaped
    if client is not None and hasattr(client, "chat") and hasattr(client.chat, "completions"):
        try:
            resp = await client.chat.completions.create(
                model=model, max_tokens=300, messages=messages, temperature=0.0,
            )
            text = resp.choices[0].message.content if resp.choices else ""
            if text and text.strip():
                return text.strip()
        except Exception as e:
            logger.debug("belief extractor: openai fallback failed (%s)", e)

    return ""
