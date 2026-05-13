# Synapse PR Conflict Watcher (browser extension)

Adds a Synapse status badge to GitHub PR pages showing pending agent
collisions in the merge queue.

## Status

**Skeleton — production-ready Manifest V3 extension structure** but
needs:
- 4 PNG icons (16/32/48/128px) — currently placeholders
- An audit endpoint deployed (default points to `audit.synapse.dev`
  which doesn't exist yet)
- Submission to the Chrome Web Store + Firefox Add-ons + Edge Add-ons

## Local install (Chrome / Edge / Brave)

1. Open `chrome://extensions/`
2. Toggle "Developer mode" on (top right)
3. Click "Load unpacked"
4. Point to this `launch/browser-extension/` directory
5. Visit any `https://github.com/*/pull/*` URL — you should see a
   "Synapse" badge near the PR title
6. Click the extension's toolbar icon to set your audit endpoint

## How it works

- **Manifest V3** service worker for background events
- **Content script** runs on every `github.com/*/pull/*` page
- Inspects the PR slug, posts to your configured audit endpoint with
  `{owner, repo, pr}`
- Endpoint returns `{conflicts: N, report_url: "..."}`
- Content script renders a green "Synapse: clear" or yellow "Synapse: N"
  badge, linked to the report

## Backend

The extension expects the audit endpoint to be a JSON API. The Synapse
GitHub Action (`launch/gh-action/`) writes its results as build
artifacts; a thin proxy at `audit.synapse.dev/api/audit` would:

1. Authenticate to the user's GitHub installation via OAuth
2. Find the latest synapse-audit-action workflow run for the PR
3. Read the conflict count from its outputs
4. Return `{conflicts, report_url}`

This proxy isn't part of the published bundle — the extension currently
shows "endpoint unreachable" until you deploy your own backend or use
the hosted version.

## Submission checklist

- [ ] Create + add 4 PNG icons (16/32/48/128)
- [ ] Deploy hosted audit endpoint OR document self-hosted setup
- [ ] Privacy policy URL (required by all browser stores)
- [ ] Chrome Web Store: $5 one-time developer fee
- [ ] Firefox Add-ons: free
- [ ] Edge Add-ons: free
- [ ] Screenshots (5 required, 1280×800)
- [ ] Promo tile (440×280)
