# Twitter / X launch thread — v0.2.8

7 tweets. Edit voice. Attach the v32 cooperative-build GIF/screenshot to tweet 1.

---

## Tweet 1 (the hook — attach screenshot of /builds/v32)

🧬 Today: 10 agentic framework SDKs collaborated on one task and built a working Flask app.

Each agent ran on a different vendor's SDK. Each played a different role. All emitted into one Synapse session.

The audit log spans all 10 vendors. The app actually runs.

Synapse v0.2.8 → 🧵

## Tweet 2 (the table — attach the role table)

The cast:

• AutoGen (MS) → API Architect
• CrewAI → Backend Engineer (main.py)
• LangGraph (LangChain) → Test Writer
• smolagents (HF) → DB Modeler
• Agno → Docs Writer
• LlamaIndex → Lint Reviewer
• Pydantic AI → Schema Validator
• OpenAI Agents SDK → Deploy Engineer
• Google ADK → Final Reviewer
• Hermes → Project Coordinator

## Tweet 3 (the proof)

Reproduce in <10 seconds after clone:

```
git clone arajgor1/synapse
pip install flask
cd bench/results/v32_app_bundle
python -c "import main; print(main.app.test_client().get('/todos').status_code)"
→ 200
```

main.py wasn't written by me. CrewAI's Backend Engineer agent wrote it. Bundle is committed.

## Tweet 4 (the unified audit log)

The thing I'm most proud of:

`envelopes.jsonl` is one Postgres table dump. INTENTION envelopes from `autogen_default`, `backend_engineer` (crewai), `tools` (langgraph), `agent` (pydantic_ai) — all tagged by vendor, all in one session.

For agentic-team compliance, this is the artifact you need.

## Tweet 5 (what existing tools don't do)

LangSmith covers LangChain.
Phoenix covers OpenInference traces.
Helicone covers OpenAI calls.

None spans 10 vendor SDKs in one session.

Synapse v0.2.8 is the first one I know of that does. Envelope log is vendor-agnostic by design.

## Tweet 6 (honesty)

Being upfront about what's not yet perfect:

• 3 of 10 OpenAI adapters dispatch tools with empty content under gpt-4o-mini (fallback rescues, but no INTENT registered for those). Anthropic route doesn't have this issue.

• HF deep NLA module ships but Modal image lacks torch by default.

## Tweet 7 (CTA)

If your team is deploying agents across vendor SDKs and needs an audit trail you can show a regulator → would love your eyes on this.

Apache 2.0. v0.2.8 just landed.

📦 github.com/arajgor1/synapse
📖 bench/PUBLIC_BENCHMARK.md
🧪 v32 bundle in the repo

What vendor adapter should be next?

---

## Optional follow-up tweets (engagement)

(a) Reply to the thread later with the actual `main.py` Flask code (12 lines) as an image.

(b) Quote-tweet positive replies with the specific carry-forward you'll prioritize for v0.2.9.

(c) If a vendor account (CrewAI, AutoGen, etc.) likes/RTs, reply with that vendor's specific INTENTION trace from the bundle.

## Posting time

Within 10 min of the HN post going up. Cross-link the HN URL in tweet 1.
