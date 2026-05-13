# Reddit launch posts — v0.2.8

## /r/MachineLearning — `[P]` flair

### Title
```
[P] Synapse v0.2.8 — 10 vendor agent SDKs collaborated to build a Flask app, with one unified audit log
```

### Body
```
I just released v0.2.8 of Synapse, an open-source coordination + audit
protocol for AI agent teams that span multiple vendor SDKs. The
headline result: ten different agentic framework runtimes (AutoGen,
CrewAI, LangGraph, smolagents, Agno, LlamaIndex, Pydantic AI, OpenAI
Agents SDK, Google ADK, Hermes) collaborated on building a Flask Todo
app, and the produced app actually runs (`GET /todos → 200`).

What v0.2.8 ships:

* `bench/results/v32_app_bundle/` — the committed end-to-end artifact.
  10 files produced by 10 different vendor agents + envelopes.jsonl
  containing INTENTION envelopes from each. Reproduce in 10 seconds.

* 10/10 V1_PASS convergence bench is byte-for-byte deterministic
  across runs (v26 = v27 — 23 intents and 9 THOUGHT envelopes match
  per adapter). Most multi-agent benchmarks I've seen flap, so worth
  flagging.

* OpenAI THOUGHT capture now has parity with Anthropic: when the model
  has no native `reasoning` field (gpt-4o-mini, gpt-4o), we capture
  `message.content` as a PSEUDO_THOUGHT envelope. This was the v27 →
  v32 gap. Fixed with the v0.2.8 release.

* HuggingFace deep NLA module (`synapse.llm_nla_hf`) — logits +
  attention + hidden-states per token for self-hosted models.
  Lazy-imported so base install doesn't pull torch.

What I'm being upfront about:

* 3 of 10 OpenAI adapters dispatch tools with empty content under
  gpt-4o-mini (langgraph, smolagents, agno). Fallback layer rescues
  the artifact but no INTENT registered. LLM-behavior issue, not
  adapter bug.

* Modal image doesn't include torch by default. HF NLA module is
  there but not exercised in CI.

Public benchmark with every iteration's results (including the
failures and the fixes): `bench/PUBLIC_BENCHMARK.md`. Apache 2.0.

Looking for:
* Feedback on which vendor adapter should be next (Vercel AI SDK?
  AWS Strands? Mastra?)
* Real-world usage data from anyone running agents across multiple
  vendor SDKs in production

Repo: https://github.com/arajgor1/synapse
```

---

## /r/LocalLLaMA

### Title
```
Synapse v0.2.8 — multi-vendor agent audit protocol, with HuggingFace deep-NLA capture for self-hosted models
```

### Body
```
Just released v0.2.8 of Synapse. Most of it is broader than this
sub's interest (cross-vendor coordination for hosted-LLM agentic
teams), but two things specifically relevant to /r/LocalLLaMA:

1. `synapse.llm_nla_hf.wrap_hf_model_for_nla()` — wraps a
   HuggingFace transformers model so every generate() call captures
   per-token logits + attention weights per layer + hidden-state
   norms, emitted as THOUGHT envelopes. Useful if you're building
   audit-grade pipelines on top of vLLM / TGI / raw HF transformers
   and want the equivalent of what closed APIs give you with their
   reasoning fields.

   Lazy import — torch is optional, base install (`pip install
   synapse-protocol`) doesn't pull it. The NLA module activates only
   when you call the wrap function.

2. The OpenAI THOUGHT capture path now falls back to message.content
   when no native reasoning field exists. Means it works against
   self-hosted OpenAI-compat APIs (Ollama, llama.cpp server, vLLM
   with --openai-api) just like it works against api.openai.com.

Repo: https://github.com/arajgor1/synapse
Full release notes: launch/RELEASE_NOTES_v0.2.8.md

Happy to answer questions, especially "would this work with my
{vLLM/Ollama/TGI} setup?"
```

---

## Posting strategy

- **Post to /r/MachineLearning ~2 hours after HN** (avoid spam-detection cross-poster filters)
- **Post to /r/LocalLLaMA the next day** (different audience; different content angle)
- For both, monitor and respond to top-level comments within the first 4 hours.
