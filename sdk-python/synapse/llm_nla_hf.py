"""Self-hosted LLM NLA capture via HuggingFace transformers.

v0.2.8 — Synapse-as-NLA for self-hosted models. Where Anthropic/OpenAI
expose only the model's text output (and sometimes thinking blocks),
self-hosted HuggingFace models give us the FULL forward pass:

  - per-token logits (top-k probability distribution)
  - per-layer attention weights (which tokens the model attended to)
  - per-layer hidden states (the residual stream — the literal NLA input)
  - per-token entropy (model uncertainty signal)

This module wraps `model.generate()` to capture this data per token and
emit one `THOUGHT` envelope per generated token (summarized) plus a
session-level `THOUGHT` with the aggregate decomposition.

Usage:

    from transformers import AutoModelForCausalLM, AutoTokenizer
    from synapse.llm_nla_hf import wrap_hf_model_for_nla

    model = AutoModelForCausalLM.from_pretrained("Qwen/Qwen2.5-7B-Instruct")
    tok = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-7B-Instruct")

    wrap_hf_model_for_nla(model, tokenizer=tok,
                         session_id="my-session", agent_id="coder")

    # Every model.generate() call now emits Synapse THOUGHT envelopes
    # containing the full NLA-equivalent data.
    out = model.generate(input_ids, max_new_tokens=200)

Operator:
    synapse audit ./trace.jsonl --include thoughts --format nla
    → renders top-k logits chart + attention-pattern summary per generated token

Privacy note: hidden states + attention weights can leak training data
characteristics. Emit only summary statistics (entropy, top-k indices,
norm-per-layer) by default; raw activations only when `raw=True` opt-in.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Optional

from synapse.messages import Envelope, MessageType, Thought
from synapse.llm_thoughts import _emit_thought

logger = logging.getLogger(__name__)


def wrap_hf_model_for_nla(
    model: Any,
    *,
    tokenizer: Any,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    parent_intention_id: Optional[str] = None,
    raw_activations: bool = False,
    top_k_logits: int = 5,
    emit_every_n_tokens: int = 8,
) -> Any:
    """Wrap a HuggingFace ``PreTrainedModel`` so every ``generate()`` call
    captures NLA-equivalent data and emits Synapse THOUGHT envelopes.

    Args:
        model: HuggingFace ``PreTrainedModel`` (any causal LM).
        tokenizer: matching tokenizer (for token-id → text decoding).
        session_id, agent_id: Synapse attribution.
        parent_intention_id: optional parent intent.
        raw_activations: if True, emit hidden_states + attentions in full.
                         Default False (summary stats only — privacy/size).
        top_k_logits: how many top tokens to capture per generation step.
        emit_every_n_tokens: emit a THOUGHT envelope every N tokens
                            (not every single token — too noisy).

    Idempotent. Patch is applied to the model instance (not the class) so
    multiple models can have different wrap configs simultaneously.
    """
    if getattr(model, "_synapse_nla_wrapped", False):
        return model

    try:
        import torch  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("synapse.wrap_hf_model_for_nla: torch not installed; "
                       "NLA capture skipped")
        return model

    original_generate = model.generate

    def _patched_generate(*args, **kwargs):
        eff_session = session_id or os.environ.get("SYNAPSE_SESSION_ID") \
                      or "hf_default_session"
        eff_agent = agent_id or "hf_agent"

        # Force the flags that give us the NLA data
        kwargs.setdefault("return_dict_in_generate", True)
        kwargs.setdefault("output_scores", True)          # logits per step
        kwargs.setdefault("output_attentions", raw_activations)
        kwargs.setdefault("output_hidden_states", raw_activations)

        t0 = time.time()
        output = original_generate(*args, **kwargs)
        elapsed_ms = (time.time() - t0) * 1000

        # Extract NLA data
        try:
            nla_payload = _extract_nla_payload(
                output=output,
                tokenizer=tokenizer,
                top_k=top_k_logits,
                emit_every_n=emit_every_n_tokens,
                raw=raw_activations,
                elapsed_ms=elapsed_ms,
            )
            # Emit one summary THOUGHT per generate() call
            asyncio.create_task(_emit_thought(
                session_id=eff_session,
                agent_id=eff_agent,
                parent_intention_id=parent_intention_id,
                block_info={
                    "text": _summarize_nla(nla_payload),
                    "kind": "hf_nla",
                    "raw_excerpt": json.dumps(nla_payload)[:1800]
                                   if not raw_activations else None,
                },
            ))
        except Exception as e:
            logger.warning("synapse.wrap_hf_model_for_nla: NLA extraction "
                          "failed (%s)", e)

        return output

    model.generate = _patched_generate
    model._synapse_nla_wrapped = True
    logger.info("synapse.wrap_hf_model_for_nla: wrapped HF model for NLA "
                "capture (session=%s agent=%s raw=%s top_k=%d every=%d)",
                session_id, agent_id, raw_activations, top_k_logits,
                emit_every_n_tokens)
    return model


def _extract_nla_payload(
    *, output: Any, tokenizer: Any, top_k: int,
    emit_every_n: int, raw: bool, elapsed_ms: float,
) -> dict:
    """Pull per-token logits/attentions/hidden_states out of HF generate output."""
    import torch  # type: ignore[import-not-found]

    seq = getattr(output, "sequences", None)
    scores = getattr(output, "scores", None) or []  # list of (batch, vocab)
    attentions = getattr(output, "attentions", None) or []
    hidden_states = getattr(output, "hidden_states", None) or []

    if seq is None:
        return {"err": "no sequences in generate output"}

    # Per-token captures
    n_new_tokens = len(scores)  # one tensor per generated token
    n_layers = 0
    if hidden_states and hidden_states[0]:
        n_layers = len(hidden_states[0])

    per_token = []
    for step in range(0, n_new_tokens, emit_every_n):
        step_data: dict = {"step": step}
        if step < len(scores):
            s = scores[step][0]  # batch=0
            probs = torch.softmax(s, dim=-1)
            top = torch.topk(probs, k=min(top_k, probs.shape[-1]))
            entropy = float(-(probs * torch.log(probs.clamp_min(1e-12))).sum())
            step_data["entropy"] = round(entropy, 4)
            step_data["top_k"] = []
            for idx, prob in zip(top.indices.tolist(), top.values.tolist()):
                try:
                    tok_text = tokenizer.decode([idx])
                except Exception:
                    tok_text = f"<id={idx}>"
                step_data["top_k"].append({
                    "token": tok_text,
                    "prob": round(float(prob), 4),
                })
        if raw and hidden_states and step < len(hidden_states):
            # hidden_states[step] is a tuple of (n_layers + 1) tensors
            # each shaped (batch, seq_len, hidden_dim)
            hs = hidden_states[step]
            step_data["hidden_norms_per_layer"] = [
                round(float(torch.linalg.norm(h[0]).item()), 4) for h in hs
            ]
        if raw and attentions and step < len(attentions):
            att = attentions[step]  # tuple of n_layers tensors
            # Attention entropy averaged across heads → uncertainty per layer
            step_data["att_entropy_per_layer"] = []
            for layer_att in att:
                # shape: (batch, n_heads, q_len, k_len)
                a = layer_att[0]  # batch=0
                # softmax is already applied; compute entropy along k_len
                ent = float(-(a * torch.log(a.clamp_min(1e-12))).sum(dim=-1).mean())
                step_data["att_entropy_per_layer"].append(round(ent, 4))
        per_token.append(step_data)

    return {
        "n_tokens": n_new_tokens,
        "n_layers": n_layers,
        "elapsed_ms": round(elapsed_ms, 1),
        "samples": per_token,
    }


def _summarize_nla(payload: dict) -> str:
    """Human-readable NLA summary for the THOUGHT.summary field."""
    n = payload.get("n_tokens", 0)
    layers = payload.get("n_layers", 0)
    samples = payload.get("samples", [])
    if not samples:
        return f"hf-nla: {n} tokens generated, no samples"
    avg_entropy = sum(s.get("entropy", 0) for s in samples) / len(samples)
    parts = [
        f"hf-nla: {n} tokens, {layers} layers,",
        f"avg-entropy={avg_entropy:.3f},",
        f"first-step top-1='{samples[0].get('top_k', [{}])[0].get('token','?')}',",
        f"last-step top-1='{samples[-1].get('top_k', [{}])[0].get('token','?')}'",
    ]
    return " ".join(parts)


__all__ = ["wrap_hf_model_for_nla"]
