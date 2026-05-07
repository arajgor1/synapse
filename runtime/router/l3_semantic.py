"""L3 semantic router — uses an LLM to decide cross-domain relevance for
messages that pass L1/L2 but might still matter to specific agents.

Design (per spec/positioning.md and the architecture doc):
- Subscribe to messages that L1+L2 say "no obvious match" or "low confidence"
- Batch them every BATCH_INTERVAL_S (or when N messages accumulated)
- Send to a cheap LLM (Gemini Flash by default) with a structured prompt
  that lists active agents' current scopes + the candidate message.
- LLM returns a routing decision; we publish to relevant agent inboxes.

Cost discipline:
- Batch of 5-10 messages per LLM call (amortizes ~80%)
- Cap routing-decision context at ~2000 tokens
- Adaptive threshold: COST_REPORTs feed back; if recent injections cost
  too much per resolution, raise the relevance bar.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from synapse.adapters.base import InferenceAdapter
from synapse.bus import Bus, session_stream
from synapse.messages import Envelope, MessageType
from synapse.state import StateGraph

logger = logging.getLogger("synapse.l3")

CONSUMER_GROUP = "l3_router"
BATCH_INTERVAL_S = 0.5
BATCH_MAX_SIZE = 8


@dataclass
class L3Stats:
    messages_seen: int = 0
    messages_routed: int = 0
    llm_calls: int = 0
    threshold: float = 0.7  # current relevance threshold (0..1)
    recent_costs_usd: list[float] = field(default_factory=list)


class L3SemanticRouter:
    """Subscribes to a session stream and runs LLM-based routing for
    messages that don't have obvious topic/scope matches.
    """

    def __init__(
        self,
        bus: Bus,
        state: StateGraph,
        session_id: str,
        backend: InferenceAdapter,
        consumer: str = "l3_a",
    ) -> None:
        self.bus = bus
        self.state = state
        self.session_id = session_id
        self.backend = backend
        self.consumer = consumer
        self.stats = L3Stats()
        self._stop = asyncio.Event()
        self._batch: list[Envelope] = []
        self._batch_lock = asyncio.Lock()

    async def run(self) -> None:
        stream = session_stream(self.session_id)
        await self.bus.ensure_group(stream, CONSUMER_GROUP)
        logger.info(
            "L3 router started session=%s consumer=%s backend=%s threshold=%.2f",
            self.session_id, self.consumer,
            self.backend.capabilities.backend_id, self.stats.threshold,
        )
        flush_task = asyncio.create_task(self._periodic_flush())
        try:
            async for entry_id, env in self.bus.consume_group(
                stream=stream, group=CONSUMER_GROUP, consumer=self.consumer,
                block_ms=500,
            ):
                self.stats.messages_seen += 1
                if self._is_l3_candidate(env):
                    async with self._batch_lock:
                        self._batch.append(env)
                        if len(self._batch) >= BATCH_MAX_SIZE:
                            await self._flush_locked()
                await self.bus.ack(stream, CONSUMER_GROUP, entry_id)
                if self._stop.is_set():
                    break
        finally:
            flush_task.cancel()
            async with self._batch_lock:
                if self._batch:
                    await self._flush_locked()

    def stop(self) -> None:
        self._stop.set()

    # -----------------------------------------------------------------
    def _is_l3_candidate(self, env: Envelope) -> bool:
        """L3 only operates on THOUGHT and BELIEF messages; INTENTION/CONFLICT
        already get L1+L2 treatment.

        Rule of thumb: if the message has structured fields the L1/L2 routers
        can match exactly (scope arrays, exact key lookups), defer to them.
        L3 picks up the squishy ones.
        """
        if env.type == MessageType.THOUGHT:
            # THOUGHT might mention things relevant to agents that didn't
            # subscribe to its declared topics
            return True
        if env.type == MessageType.BELIEF:
            # BELIEFs already route via the coordinator's divergence detector,
            # so L3 is supplementary — only on first-seen keys
            return False  # Defer fully to coordinator for v1
        return False

    async def _periodic_flush(self) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(BATCH_INTERVAL_S)
            async with self._batch_lock:
                if self._batch:
                    await self._flush_locked()

    async def _flush_locked(self) -> None:
        if not self._batch:
            return
        batch = self._batch
        self._batch = []
        try:
            await self._route_batch(batch)
        except Exception:
            logger.exception("L3 batch routing error")

    # -----------------------------------------------------------------
    async def _route_batch(self, batch: list[Envelope]) -> None:
        # Pull active agents + their owned scopes
        async with self.state.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, scopes_owned, subscribes
                   FROM agents WHERE session_id = $1 AND status = 'active'""",
                self.session_id,
            )
        agents_summary = [
            {
                "agent_id": r["id"],
                "owns": list(r["scopes_owned"]),
                "subs": list(r["subscribes"]),
            }
            for r in rows
        ]
        if len(agents_summary) < 2:
            return  # No one to route to

        # Build LLM prompt
        prompt = self._build_prompt(batch, agents_summary)
        try:
            decision = await self._llm_decide(prompt)
        except Exception as e:
            logger.warning("L3 LLM call failed: %s", e)
            return

        self.stats.llm_calls += 1
        # Apply the decision: each entry is {message_idx, route_to, summary}
        for item in decision.get("routes", []):
            try:
                idx = int(item.get("message_idx", -1))
                relevance = float(item.get("relevance", 0))
                route_to = item.get("route_to", [])
                summary = item.get("summary", "")
            except Exception:
                continue
            if idx < 0 or idx >= len(batch):
                continue
            if relevance < self.stats.threshold:
                continue
            src = batch[idx]
            for target_agent in route_to:
                env_out = Envelope.make(
                    type=MessageType.THOUGHT,
                    agent_id="l3-router",
                    session_id=self.session_id,
                    payload={
                        "summary": summary or f"Cross-domain signal from {src.agent_id}",
                        "topics": [],
                        "raw_excerpt": json.dumps(src.payload)[:500],
                    },
                    parent_msg_id=src.msg_id,
                    tenant_id=src.tenant_id,
                )
                await self.bus.publish_inbox(target_agent, env_out)
                self.stats.messages_routed += 1
        logger.info(
            "L3 batch: %d messages -> %d routed (threshold=%.2f, total LLM calls=%d)",
            len(batch), self.stats.messages_routed, self.stats.threshold, self.stats.llm_calls,
        )

    def _build_prompt(
        self, batch: list[Envelope], agents: list[dict[str, Any]]
    ) -> str:
        agents_block = "\n".join(
            f"- {a['agent_id']}: owns={a['owns']} subscribes={a['subs']}"
            for a in agents
        )
        messages_block = "\n".join(
            f"[{i}] from={env.agent_id} type={env.type.value} "
            f"payload_summary={json.dumps(env.payload, default=str)[:300]}"
            for i, env in enumerate(batch)
        )
        return (
            "You are the L3 router for a multi-agent coordination system.\n"
            "Decide which messages should be routed to which agents based on "
            "non-obvious semantic relevance (NOT exact topic/scope match).\n\n"
            f"Active agents:\n{agents_block}\n\n"
            f"Messages to consider:\n{messages_block}\n\n"
            "Output a JSON object: {\"routes\": [{\"message_idx\": 0, \"route_to\": [\"agent_id\"], "
            "\"relevance\": 0.0_to_1.0, \"summary\": \"why\"}]}.\n"
            "Only include routes you would push (relevance > 0.7 typical). "
            "If no routing needed, return {\"routes\": []}."
        )

    async def _llm_decide(self, prompt: str) -> dict[str, Any]:
        # Force JSON output. For Gemini, response_mime_type guarantees parseable
        # JSON. Other backends ignore unknown params silently — they'll still
        # work, just with the markdown-fence-tolerant parser below as fallback.
        handle = await self.backend.start_stream(
            messages=[{"role": "user", "content": prompt}],
            params={
                "max_tokens": 800,
                "temperature": 0.0,
                "response_mime_type": "application/json",
            },
        )
        chunks: list[str] = []
        async for tok in self.backend.read_tokens(handle):
            chunks.append(tok.text)
            # Hard cap to bound cost; never cancel before 4000 chars to give
            # the LLM enough room for the full JSON.
            if sum(len(c) for c in chunks) > 4000:
                await self.backend.cancel(handle)
                break
        text = "".join(chunks).strip()
        # Extract JSON — handle markdown fences and stray surrounding text.
        if "```" in text:
            parts = text.split("```")
            for p in parts:
                p = p.lstrip("json").lstrip("\n").strip()
                if p.startswith("{"):
                    text = p
                    break
        # Take from first '{' to last '}' to handle prose around the JSON
        if "{" in text and "}" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            text = text[start:end]
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(
                "L3 LLM returned non-JSON (parsed up to %d chars): %r",
                len(text), text[:300],
            )
            return {"routes": []}

    # -----------------------------------------------------------------
    def adjust_threshold(self, recent_avg_cost_usd: float) -> None:
        """Adaptive threshold based on cost feedback.

        If recent L3-driven actions cost too much, raise the bar.
        Simple proportional response: threshold tracks toward higher when
        cost_per_action exceeds a target.
        """
        TARGET_COST = 0.001  # $0.001 per L3 routing
        if recent_avg_cost_usd > TARGET_COST * 2:
            self.stats.threshold = min(0.95, self.stats.threshold + 0.05)
            logger.info("L3 threshold raised to %.2f", self.stats.threshold)
        elif recent_avg_cost_usd < TARGET_COST * 0.5 and self.stats.threshold > 0.5:
            self.stats.threshold = max(0.5, self.stats.threshold - 0.05)
            logger.info("L3 threshold lowered to %.2f", self.stats.threshold)
