"""Synapse Coordinator — event-driven LLM-mediated session-wide reasoner.

Subscribes to the session stream via Redis consumer group `coordinator`.
Wakes on:
- BLOCK messages → route to capable peers, synthesize guidance if needed
- BELIEF messages → re-run divergence detection; emit clarification signal
- 30s background tick → summarize session state for context window
- COST_REPORT messages → adjust routing thresholds

Model-agnostic: takes any InferenceAdapter for its own LLM calls. Default
is Gemini 2.5 Flash (cheap + free on Vertex AI).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from typing import Any, Optional

from synapse.adapters.base import InferenceAdapter
from synapse.bus import Bus, agent_inbox, session_stream
from synapse.messages import (
    Belief,
    Block,
    Conflict,
    ConflictingIntention,
    Envelope,
    MessageType,
)
from synapse.state import StateGraph
from runtime.coordinator.belief_divergence import (
    AgentBelief,
    beliefs_from_db_rows,
    detect_divergences,
)

logger = logging.getLogger("synapse.coordinator")

CONSUMER_GROUP = "coordinator"
SUMMARY_INTERVAL_S = 30.0


class Coordinator:
    """Long-running coordinator process. Single instance per session."""

    def __init__(
        self,
        bus: Bus,
        state: StateGraph,
        session_id: str,
        backend: Optional[InferenceAdapter] = None,
        consumer: str = "c1",
    ) -> None:
        self.bus = bus
        self.state = state
        self.session_id = session_id
        self.backend = backend  # If None, use rule-based fallbacks only
        self.consumer = consumer
        self._stop = asyncio.Event()
        self._summary_text: str = ""
        self._last_summary_at: float = 0.0
        self._cost_total_usd: float = 0.0

    async def run(self) -> None:
        stream = session_stream(self.session_id)
        await self.bus.ensure_group(stream, CONSUMER_GROUP)
        logger.info(
            "Coordinator started for session=%s consumer=%s backend=%s",
            self.session_id, self.consumer,
            self.backend.capabilities.backend_id if self.backend else "rules-only",
        )

        async for entry_id, env in self.bus.consume_group(
            stream=stream,
            group=CONSUMER_GROUP,
            consumer=self.consumer,
            block_ms=2000,
        ):
            try:
                await self._dispatch(env)
            except Exception:
                logger.exception("Coordinator error processing %s", env.msg_id)
            finally:
                await self.bus.ack(stream, CONSUMER_GROUP, entry_id)
            if self._stop.is_set():
                break

    def stop(self) -> None:
        self._stop.set()

    # -----------------------------------------------------------------
    async def _dispatch(self, env: Envelope) -> None:
        if env.type == MessageType.BLOCK:
            await self._handle_block(env)
        elif env.type == MessageType.BELIEF:
            await self._handle_belief(env)
        elif env.type == MessageType.COST_REPORT:
            await self._handle_cost(env)

    # -----------------------------------------------------------------
    async def _handle_block(self, env: Envelope) -> None:
        block = Block.model_validate(env.payload)
        logger.info(
            "BLOCK from %s: blocker=%r needed=%r urgency=%s",
            env.agent_id, block.blocker, block.needed, block.urgency,
        )

        # Find peer agents in the same session
        async with self.state.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id FROM agents WHERE session_id = $1 AND id != $2 AND status = 'active'",
                env.session_id, env.agent_id,
            )
        peers = [r["id"] for r in rows]
        if not peers:
            logger.info("BLOCK has no peers to escalate to.")
            return

        # Synthesize guidance via LLM if backend available; otherwise route raw
        guidance: Optional[str] = None
        if self.backend is not None and block.urgency in ("medium", "high"):
            guidance = await self._llm_guidance_for_block(env.agent_id, block)

        # Route to all peers (let them filter by their own subscriptions later)
        body = {
            "from_agent": env.agent_id,
            "blocker": block.blocker,
            "needed": block.needed,
            "attempted": block.attempted,
            "urgency": block.urgency,
            "guidance": guidance,
        }
        forwarded = Envelope.make(
            type=MessageType.BLOCK,
            agent_id="coordinator",
            session_id=env.session_id,
            payload=body,
            parent_msg_id=env.msg_id,
            tenant_id=env.tenant_id,
        )
        for peer in peers:
            await self.bus.publish_inbox(peer, forwarded)
        logger.info("Forwarded BLOCK to %d peer(s) with guidance=%s",
                    len(peers), bool(guidance))

    async def _llm_guidance_for_block(self, blocked_agent: str, block: Block) -> Optional[str]:
        if self.backend is None:
            return None
        prompt = (
            f"Agent {blocked_agent} is blocked.\n"
            f"Blocker: {block.blocker}\n"
            f"Needed: {block.needed}\n"
            f"Already attempted: {', '.join(block.attempted) or '(none)'}\n"
            f"Urgency: {block.urgency}\n\n"
            f"In one short paragraph (under 60 words), suggest a concrete next step "
            f"the agent's peers could take to unblock it. Be specific."
        )
        try:
            handle = await self.backend.start_stream(
                messages=[{"role": "user", "content": prompt}],
                params={"max_tokens": 100},
            )
            chunks = []
            async for tok in self.backend.read_tokens(handle):
                chunks.append(tok.text)
                if sum(len(c) for c in chunks) > 600:
                    await self.backend.cancel(handle)
                    break
            return "".join(chunks).strip()
        except Exception as e:
            logger.warning("Coordinator LLM guidance failed: %s", e)
            return None

    # -----------------------------------------------------------------
    async def _handle_belief(self, env: Envelope) -> None:
        b = Belief.model_validate(env.payload)
        # Persist to state graph
        async with self.state.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO beliefs (agent_id, session_id, tenant_id, key, value,
                                     confidence, source, evidence, updated_at)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, now())
                ON CONFLICT (agent_id, key) DO UPDATE SET
                  value = EXCLUDED.value,
                  confidence = EXCLUDED.confidence,
                  source = EXCLUDED.source,
                  evidence = EXCLUDED.evidence,
                  updated_at = now()
                """,
                env.agent_id, env.session_id, env.tenant_id, b.key,
                json.dumps(b.value), b.confidence, b.source, b.evidence,
            )

        # Re-detect divergences across all session beliefs for this key
        async with self.state.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT agent_id, key, value, confidence, source
                FROM beliefs WHERE session_id = $1 AND key = $2
                """,
                env.session_id, b.key,
            )
        beliefs = beliefs_from_db_rows([{**r, "value": json.loads(r["value"]) if isinstance(r["value"], str) else r["value"]} for r in rows])
        divergences = detect_divergences(beliefs)
        if not divergences:
            return

        d = divergences[0]
        if d.severity < 0.3:
            logger.debug("Low-severity divergence on %s; ignoring.", d.key)
            return

        logger.warning(
            "Divergence on '%s': %d agents disagree (severity=%.2f, distinct=%s)",
            d.key, len(d.agents), d.severity, list(d.distinct_values),
        )

        # Synthesize a clarification message via LLM if available
        clarification = await self._llm_clarify_divergence(d)
        # Send to each agent participating in the divergence as a BLOCK signal
        # of kind 'divergence' (encoded as topic for now; v1.1 may add a
        # dedicated BELIEF_DIVERGENCE message type).
        body = {
            "blocker": f"Belief divergence on '{d.key}'",
            "needed": clarification or (
                f"Reconcile distinct values: {list(d.distinct_values)}. "
                f"Verify against ground truth and update via a fresh BELIEF."
            ),
            "attempted": [],
            "urgency": "medium" if d.severity < 0.7 else "high",
            "topics": [d.key],
        }
        env_out = Envelope.make(
            type=MessageType.BLOCK,
            agent_id="coordinator",
            session_id=env.session_id,
            payload=body,
            parent_msg_id=env.msg_id,
            tenant_id=env.tenant_id,
        )
        for ab in d.agents:
            await self.bus.publish_inbox(ab.agent_id, env_out)

    async def _llm_clarify_divergence(self, d: Any) -> Optional[str]:
        if self.backend is None:
            return None
        descriptions = "\n".join(
            f"- {b.agent_id}: value={b.value!r} confidence={b.confidence:.2f} source={b.source}"
            for b in d.agents
        )
        prompt = (
            f"Multiple agents hold distinct beliefs about '{d.key}':\n{descriptions}\n\n"
            f"In one short paragraph (under 50 words), advise the agents on how to "
            f"reconcile this. Suggest the most authoritative source they could check."
        )
        try:
            handle = await self.backend.start_stream(
                messages=[{"role": "user", "content": prompt}],
                params={"max_tokens": 80},
            )
            chunks: list[str] = []
            async for tok in self.backend.read_tokens(handle):
                chunks.append(tok.text)
                if sum(len(c) for c in chunks) > 400:
                    await self.backend.cancel(handle)
                    break
            return "".join(chunks).strip()
        except Exception as e:
            logger.warning("Coordinator clarify failed: %s", e)
            return None

    # -----------------------------------------------------------------
    async def _handle_cost(self, env: Envelope) -> None:
        usd = float(env.payload.get("estimated_usd", 0) or 0)
        self._cost_total_usd += usd
        logger.debug("Cost report from %s: $%.5f (session total $%.4f)",
                     env.agent_id, usd, self._cost_total_usd)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main(
    session_id: str,
    redis_url: str,
    postgres_dsn: str,
    consumer: str,
    backend_name: str,
) -> None:
    logging.basicConfig(
        level=os.getenv("SYNAPSE_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    bus = Bus(redis_url)
    state = StateGraph(postgres_dsn)
    await bus.connect()
    await state.connect()

    backend: Optional[InferenceAdapter] = None
    if backend_name and backend_name != "none":
        try:
            if backend_name == "gemini":
                from synapse.adapters.hosted import GeminiAdapter
                backend = GeminiAdapter(
                    project=os.environ.get("SYNAPSE_GCP_PROJECT"),
                    max_tokens=128,
                )
            elif backend_name == "anthropic":
                from synapse.adapters.hosted import AnthropicAdapter
                backend = AnthropicAdapter(max_tokens=128)
        except Exception as e:
            logger.warning("Coordinator backend init failed: %s; using rules-only.", e)
            backend = None

    coord = Coordinator(bus, state, session_id, backend=backend, consumer=consumer)
    try:
        await coord.run()
    finally:
        await bus.close()
        await state.close()


def cli() -> None:
    parser = argparse.ArgumentParser(description="Synapse Coordinator")
    parser.add_argument("--session", required=True)
    parser.add_argument(
        "--redis-url",
        default=os.getenv("SYNAPSE_REDIS_URL", "redis://localhost:6379/0"),
    )
    parser.add_argument(
        "--postgres-dsn",
        default=os.getenv(
            "SYNAPSE_POSTGRES_DSN",
            "postgresql://synapse:synapse_dev@localhost:5432/synapse",
        ),
    )
    parser.add_argument("--consumer", default="c1")
    parser.add_argument("--backend", default=os.getenv("SYNAPSE_COORDINATOR_BACKEND", "gemini"))
    args = parser.parse_args()
    asyncio.run(main(args.session, args.redis_url, args.postgres_dsn, args.consumer, args.backend))


if __name__ == "__main__":
    cli()
