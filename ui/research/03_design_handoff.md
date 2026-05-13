# Synapse UI — Design Handoff (v0.2.8)

## Information architecture

```
/                        Landing
  └─ Hero band           "Synapse — audit + compliance for agentic teams"
  └─ Latest build card   v32 (cross-vendor cooperative build), 1-line verdict + link
  └─ Active sessions     (existing) — live gateway sessions

/builds/[id]             Cooperative-build view (NEW)
  └─ Verdict band        10 vendors × 7 intents × 1 running app
  └─ Agent grid          10 cards: framework / role / file / status
  └─ Artifact viewer     Side panel — click any file to preview
  └─ Envelope timeline   Scrollable list of INTENTIONs in chrono order
  └─ Reproduce footer    Commit hash + run command

/sessions/[id]           Live session view (EXISTING) — keep + polish header
```

## Routes / pages

| Route | Status | What changes |
|---|---|---|
| `/` | Existing | Add hero band + latest-build card |
| `/builds/v32` | **NEW** | Full cooperative-build view |
| `/builds/[id]` | **NEW (route)** | Parameterized; v32 is just the first |
| `/sessions/[id]` | Existing | Add "back to build" breadcrumb if launched from a build |

## API / data

- `/api/builds/v32` (new) — serves the parsed v32 bundle as JSON:
  ```json
  {
    "id": "v32",
    "session": "v32_app_1778635046",
    "commit": "6340949",
    "summary": {
      "vendor_count": 10,
      "files_written": 10,
      "intents": 8,
      "app_runs": true,
      "app_check": "GET /todos returned 200"
    },
    "roles": [
      { "framework": "autogen", "role": "API Architect", "file": "api_spec.md",
        "bytes": 177, "via_fallback": false, "preview": "...", "vendor": "Microsoft" },
      ...
    ],
    "envelopes": [ { "type": "INTENTION", "agent_id": "...", "ts_ms": ..., ... } ],
    "files": { "main.py": "<source>", ... }
  }
  ```
  Backed by reading `bench/results/v32_app_bundle/envelopes.jsonl` + the
  files in that directory at request time. No DB, no gateway.

## Components (additions)

| Component | Purpose | Reuses |
|---|---|---|
| `VerdictBand` | Hero numerals + app-runs badge | New |
| `VendorAgentGrid` | 10-card grid of framework→role→file | Extends `AgentGrid` |
| `ArtifactPreview` | Syntax-highlighted file viewer | New, no external lib (basic `<pre>` + token regex) |
| `EnvelopeTimeline` | Compact chrono list of envelopes with vendor chips | Adapts `EventStream` |
| `ReproduceBlock` | "Run it yourself" code block + copy button | New |
| `LatestBuildCard` | Landing-page card | New |

## Visual / color tokens

Keep existing tokens (already in `tailwind.config.ts`):
- `bg-bg` (deepest), `bg-bg-panel` (cards), `bg-bg-panel2` (nested)
- `border-line` (1px borders)
- `text-text-primary`, `text-text-secondary`, `text-muted`
- `text-accent-blue` (primary), `text-accent-green` (success / app-runs),
  `text-accent-red` (failures), `text-accent-amber` (replay / fallback)

New tokens to add (if missing):
- `text-accent-violet` for "fallback used" badge (distinct from amber-as-replay)

## Vendor → display-name mapping

Hard-coded in `lib/vendors.ts`:
```
autogen        → "Microsoft AutoGen"     (badge: "MS")
crewai         → "CrewAI"                (badge: "CW")
langgraph      → "LangChain LangGraph"   (badge: "LC")
hermes         → "Hermes (Synapse-native)" (badge: "HM")
smolagents     → "HuggingFace smolagents" (badge: "HF")
agno           → "Agno"                  (badge: "AG")
llama_index    → "LlamaIndex"            (badge: "LI")
pydantic_ai    → "Pydantic AI"           (badge: "PY")
openai_agents  → "OpenAI Agents SDK"     (badge: "OA")
google_adk     → "Google ADK"            (badge: "GG")
```

## Copy (verbatim)

**Landing hero**:
> # Synapse
> Audit + coordination layer for **agentic teams that span vendors**.
> One session, ten SDKs, one envelope log.

**Latest build card**:
> ### Latest cooperative build: v32
> 10 agents from 10 different framework SDKs collaborated on one Synapse
> session to build a Flask Todo app. The app runs.
> → View the bundle

**Build verdict band**:
> Cross-framework cooperative build
> session = v32_app_1778635046 · commit = 6340949
>
> [10 vendors]  [10 files]  [8 intents]  [App runs: ✅ GET /todos → 200]

**Reproduce footer**:
> Reproduce locally:
> ```
> git checkout 6340949
> cd bench/results/v32_app_bundle && python -c "import main; main.app.run(port=5001)"
> # then: curl localhost:5001/todos
> ```

## Acceptance criteria

A reviewer landing on `/builds/v32` cold (no prior context) must be able to:

1. Within 5s: read the headline and know "10 SDKs, 1 product, app runs".
2. Within 15s: scan the agent grid and see which vendor produced which file.
3. Within 30s: click a file and see its source.
4. Within 60s: copy the reproduce command and run it themselves.
5. Within 90s: open the envelope timeline and read 5 actual INTENTION rows.

If any of (1)–(4) fails on first viewing without scrolling instruction, we
ship a fix before calling it polished.

## Build order (execution)

1. `lib/vendors.ts` — vendor metadata.
2. `lib/bundle.ts` — bundle parser/loader (works in browser and in API route).
3. `app/api/builds/[id]/route.ts` — serves the bundle JSON.
4. `components/VerdictBand.tsx` — hero numerals.
5. `components/VendorAgentGrid.tsx` — 10 framework cards.
6. `components/ArtifactPreview.tsx` — file viewer + side panel.
7. `components/EnvelopeTimeline.tsx` — chrono list.
8. `components/ReproduceBlock.tsx` — copy-block.
9. `app/builds/[id]/page.tsx` — page composition.
10. `app/page.tsx` — add hero band + latest-build card.
11. `app/layout.tsx` — set page title and meta.
12. Visual QA — run `npm run dev`, walk through acceptance criteria.

## Non-goals for handoff

- Animation. Static dark dashboard, no entrance transitions.
- Icon library. Use unicode + small SVG inline; no extra deps.
- Authentication. Public, local.
