# Synapse UI — Research Plan (v0.2.8)

> **Honesty note**: This is a synthesis-from-known-context exercise, not field
> interviews. The product has 1 active operator (the founder) and a market
> thesis ("agentic teams need a compliance layer"). The personas, JTBD, and
> "interview findings" below are derived from: (a) the founder's stated needs
> in this build session, (b) explicit Synapse positioning in README + spec,
> (c) the v32 artifact bundle that proves the cross-vendor scenario is real.
> Anything marked **inferred** should be re-validated with real users before
> being treated as a fact.

## 1. Objective

Decide what the Synapse UI must show **today** so a viewer can answer, in
under 30 seconds:

> "Did 10 different agentic SDKs cooperate to build one real artifact, and
> can I audit the whole thing?"

The v0.2.8 release shipped the cross-vendor cooperative build (v32 bundle).
The current UI predates it — it's a generic per-session observability dash
hooked to a live gateway. It does NOT surface the value prop the v0.2.8
release actually proves.

## 2. Personas (3)

### P1 — "Maya", Compliance / Risk Officer at an enterprise running agentic teams
- **Goal**: prove SOC2 / EU AI Act compliance for autonomous multi-agent workflows.
- **Pain**: vendor-specific traces (LangSmith, Phoenix, Helicone) don't unify across SDKs. She can't answer "which agent did what" when the team spans 3 vendors.
- **Today**: she rejects internal proposals to deploy agentic teams because she can't audit them.
- **Inferred** — based on market thesis, no direct interview.

### P2 — "Dev", ML Platform Engineer integrating Synapse
- **Goal**: drop Synapse into an existing multi-SDK pipeline, see the audit trail without rewriting the whole stack.
- **Pain**: 5-min skim of docs → demo viewer that shows "yes this actually works" without him reading SDK source.
- **Today**: 30 seconds on the landing page → either bounce or `pip install`.
- **Inferred** — based on the demo-driven adoption pattern for similar tools.

### P3 — "Aaditya", the founder dogfooding for investor / blog demos
- **Goal**: one screen that screams "10 vendors → 1 product → unified audit".
- **Pain**: the current per-session dash is generic; doesn't tell the v0.2.8 story.
- **Today**: would screenshot a terminal log or git diff for demos, which is unprofessional.
- **Validated** — from this build session.

## 3. Jobs To Be Done

1. **JTBD-1 (compliance)** — *When my agentic team builds something across vendors, I want a single audit log so I can prove who did what to a regulator.*
2. **JTBD-2 (debug)** — *When an agent run fails in production, I want to see which vendor SDK fired which envelope so I can debug without grep-ing 5 different trace formats.*
3. **JTBD-3 (sell)** — *When I'm prepping a demo for investors / users, I want a screen that proves "real product built end-to-end by an agentic team" without needing me to narrate.*

## 4. Research questions

| # | Question | Method | Status |
|---|---|---|---|
| Q1 | What's the first thing a viewer should see when they hit `/`? | Founder interview (this session) | Answered: cross-vendor compliance hero |
| Q2 | How important is "running app" proof vs. just "audit log present"? | Founder interview | Answered: both required, app proof is the headline |
| Q3 | What primary nav structure works? Per-session or per-build-run? | Founder interview | Answered: per-build-run as headline; per-session as detail view |
| Q4 | What must show on the cooperative-build view? | Founder interview + JTBD analysis | Answered: 10 agents, 10 produced files, envelope log, app-runs verdict |
| Q5 | Does the live gateway need to be running for the demo to work? | UX walk-through | Answered: NO — static bundle load required for offline demos |
| Q6 | What's the lowest-effort path to "polished"? | Component audit | Answered: dark-on-dark IBM-Carbon-ish, monospace data, copy as headline |

## 5. Concept reactions (forced choices)

Three concepts were considered for the headline view:

| Option | Pros | Cons |
|---|---|---|
| A. Single-session timeline view (current) | Exists | Doesn't show the cross-vendor story |
| **B. Cooperative-build dashboard (NEW)** | Directly tells the v0.2.8 story; one screen | Requires a new page |
| C. Vendor matrix (10×N grid of frameworks × features) | Visual punch | Doesn't show the artifact or proof |

**Pick: B.** Land on a Cooperative-Build view; keep A as the per-session
detail view; defer C as a future marketing page.

## 6. Deliverables

- ✅ This plan
- → Synthesis report (next): themes + must-haves
- → Design handoff: components, IA, copy, color tokens
- → Implementation: actual code under `ui/src/`

## 7. Out of scope for v0.2.8 UI

- BYO-LLM picker UI
- Org / multi-tenant management
- Cost forecasting beyond per-session sum
- Real-time replay over WebRTC (Carry-forward)
- Mobile (Carry-forward)
