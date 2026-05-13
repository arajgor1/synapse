# Synapse UI — Research Synthesis (v0.2.8)

## Themes (affinity-mapped)

### T1 — "Audit trail must be cross-vendor or it's pointless"
Source: JTBD-1 (Maya), v0.2.8 thesis ("compliance for agentic teams"), v32
envelope log shows agents from autogen_default, backend_engineer (crewai),
tools (langgraph), agent (pydantic_ai), etc.

→ UI implication: the cooperative-build view must visually *prove* the
   cross-vendor nature. Show vendor logos / framework names next to every
   envelope, every artifact.

### T2 — "Running app > talking about a running app"
Source: Founder demand "actual app up and running on local machine"
(this session, verbatim). The v32 bundle's main.py serves HTTP 200 on
GET/POST /todos *locally*.

→ UI implication: a prominent "App runs: ✅ GET /todos → 200" verdict at
   the top, with a "Run it yourself" affordance (the bundle path + a
   one-liner command).

### T3 — "Demo without infra"
Source: Q5 above + the reality that the gateway/Redis/Postgres aren't
running on most viewers' machines.

→ UI implication: must support **static-bundle mode** — point at
   `bench/results/v32_app_bundle/envelopes.jsonl` + the produced files
   and render the full story without any backend.

### T4 — "Monospace + dark + no chrome"
Source: existing component style + technical audience (P2, P3).

→ UI implication: keep the existing dark palette (`bg-bg-panel`,
   `text-text-secondary`, etc.); avoid adding marketing chrome (gradients,
   hero illustrations) that would clash.

### T5 — "Skim in 5s, deep-dive on demand"
Source: P2's bounce-rate concern.

→ UI implication: above-the-fold must answer "what did this prove?" with
   3-5 numerals (vendors, files, intents, app-runs verdict). All detail
   panels collapsed by default.

## Impact / Effort matrix

| Insight | Impact | Effort | Decision |
|---|---|---|---|
| Cooperative-build view as new headline page | High | M | **Build** |
| Static bundle loader (no gateway needed) | High | S | **Build** |
| Vendor labels on every envelope row | High | XS | **Build** |
| Produced-file preview pane | High | S | **Build** |
| "Run it locally" copy block | Medium | XS | **Build** |
| Per-session live view (existing) | Medium | 0 (exists) | **Keep, polish** |
| Cost forecasting | Low | M | Defer |
| BYO-LLM picker | Low | L | Defer |
| Animated agent collaboration replay | High | L | **Defer to v0.2.9** |

## Must-haves for v0.2.8 UI

1. **New page** `/builds/v32` (or generic `/builds/[id]`) — the cooperative-build view.
2. **Hero band**: "10 vendors × 1 session × app runs ✅" with the 4-5 key numerals.
3. **Vendor → file mapping grid**: which framework produced which artifact, with `direct capture` vs `fallback` badge.
4. **Envelope timeline**: scrollable list of the bundle's INTENTIONs, agent name + vendor inferred from agent_id.
5. **Artifact viewer**: click a file → syntax-highlighted preview in a side panel.
6. **"Run it yourself" footer**: the literal `python -m flask --app main run` line and the test client output we captured.
7. **Landing page (`/`)**: keep the live-session list, but add a "Latest build" card at the top pointing at v32.
8. **Polish**: consistent header, breadcrumbs, link the bundle commit hash.

## Anti-features (explicitly NOT building)

- Login / auth — local-first dogfood; defer to org rollout.
- Marketing gradient hero — clashes with the technical aesthetic.
- Sidebar nav with 5+ sections — over-engineered for one-product-one-session.
- Charts as decoration — every chart must answer a JTBD question.

## Risk register

- **R1**: real users may want different headline numerals. Mitigation: keep the hero band data-driven from the bundle so it's easy to swap.
- **R2**: bundle parsing brittle. Mitigation: same `useSession` reducer, just fed from a JSON fetch instead of a WebSocket.
- **R3**: dark-only theme excludes light-mode previewers. Acceptable for v0.2.8; revisit when we add docs.
