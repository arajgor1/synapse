# Deploying the Synapse hosted demo

This is a static site — no backend, no build step. Browser-side audit
runs entirely in JavaScript on user-supplied trace files. Deploy
anywhere that serves static HTML.

## Recommended: Cloudflare Pages (free, fast, custom domain)

```bash
# 1. Create the project on Cloudflare Pages
#    https://dash.cloudflare.com → Workers & Pages → Create → Pages → Direct Upload

# 2. Drag-and-drop this entire `launch/hosted-audit/` directory

# 3. Set custom domain (e.g., audit.synapse.dev) under Custom Domains

# Or via CLI:
npx wrangler pages deploy launch/hosted-audit --project-name=synapse-audit
```

Total time: ~5 minutes. Free.

## Alternative: Vercel

```bash
cd launch/hosted-audit
npx vercel --prod
```

## Alternative: GitHub Pages

```bash
# In repo settings → Pages → Source: deploy from a branch → main, /launch/hosted-audit
# Site lives at https://arajgor1.github.io/synapse/launch/hosted-audit/
```

## Files in this directory

| File | What |
|---|---|
| `landing.html` | Marketing landing page (the actual launch URL) |
| `index.html` | Drop-trace-get-conflicts audit tool (works in browser) |
| `benchmark.html` | Auto-rendered benchmark dashboard |
| `explorer.html` | D3 force-graph visualization of agent collisions |
| `samples/` | Pre-loaded sample traces (Bedrock, Vertex, Azure, multi-orch) |
| `agenticflict_benchmark.json` | Symlink/copy from `bench/results/` so benchmark.html can fetch it |

## Update the benchmark dashboard

Whenever a new benchmark runs, copy the result JSON:

```bash
cp bench/results/agenticflict_benchmark.json launch/hosted-audit/agenticflict_benchmark.json
```

The `benchmark.html` page fetches this file and re-renders. (Falls back
to a hardcoded snapshot if the file isn't present.)

## Set up `audit.synapse.dev`

If you own `synapse.dev` (or buy it):

1. In Cloudflare DNS for synapse.dev, create a CNAME:
   `audit` → `synapse-audit.pages.dev`
2. In Cloudflare Pages → synapse-audit → Custom domains → Add `audit.synapse.dev`
3. SSL provisions automatically.

Total cost: $9/yr for the domain, $0 for hosting.
