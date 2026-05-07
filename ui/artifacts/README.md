# Synapse Dashboard (artifact)

A polished, single-HTML dashboard for a live Synapse session. Self-contained — no
backend, no external fonts, no network calls. Drop `synapse-dashboard.html` into
a browser, share it as a Claude artifact, or embed in a slide.

## Files

- `synapse-dashboard.html` — bundled single-file artifact (~348 KB).
- `synapse-dashboard-src/` — Vite + React + TypeScript source (re-editable).

## What it shows

- **Top bar**: `Synapse` serif wordmark, `session: ecom_v1` chip, live pulse, uptime.
- **KPI strip**: Agents active, Intentions, Conflicts caught, Auto-merges.
- **Agent grid**: 8 tiles mixing `Hermes` / `LangGraph` / `CrewAI` framework badges,
  current intentions, and per-agent status pulse (active / deliberating / blocked / merged).
- **Live event stream**: timeline of `INTENTION` / `RESOLUTION` / `CONFLICT` / `BELIEF`
  envelopes with relative ages and meta tags. Filterable by envelope kind.
- **Conflict drawer**: slides in over the dashboard when you click a `CONFLICT`
  row (or one of the items in the *Active conflicts* card). Shows the overlap
  scope, both agents' intentions, the policy decision (`auto_merge`, `defer`,
  etc.), severity, prior count, and resolution time.
- **Belief divergence panel**: side-by-side `revenue_formula` from `cleaner` vs
  `analyst` with confidence bars.

Sample data is hardcoded in `src/synapse/data.ts` and modeled after
`bench/results/v02_w4_auto_merge_*.json` and
`bench/results/v02_w5_belief_divergence_*.json`.

## Re-build the bundle

From this directory:

```bash
cd synapse-dashboard-src
pnpm install                 # one-time
bash ~/.claude/skills/web-artifacts-builder/scripts/bundle-artifact.sh
cp bundle.html ../synapse-dashboard.html
```

(Substitute the actual path to the `web-artifacts-builder` skill if it lives
elsewhere on your machine — on Windows it's typically under
`C:\Users\<you>\AppData\Roaming\Claude\local-agent-mode-sessions\skills-plugin\...\skills\web-artifacts-builder`.)

To iterate locally with hot-reload:

```bash
cd synapse-dashboard-src
pnpm dev
```

## Design notes (intentional anti-AI-slop choices)

- No purple gradients. Single accent: an electric tangerine (`hsl(18 88% 52%)`)
  on a warm bone background.
- Mixed corner radii: full pills for chips, soft `rounded-md` for cards, sharp
  `rounded-sm` for inline tags and code-like containers.
- Serif (Iowan Old Style / Charter / Georgia) for the wordmark and section
  titles, system-ui for body copy, JetBrains Mono / SFMono / Consolas for
  envelope IDs and code-y values. **No Inter.**
- Real layout density: persistent left rail nav, KPI strip, four-column agent
  grid, two-column event-stream + active-conflicts pane, full-width belief
  panel. No giant centered hero.
- Custom envelope semantic palette baked into Tailwind:
  `envelope-intention` (steel blue), `envelope-resolution` (forest green),
  `envelope-conflict` (rust), `envelope-belief` (muted plum).

## Untouched

This artifact lives in `ui/artifacts/`. The existing Next.js app at
`ui/src/` is **not modified**.
