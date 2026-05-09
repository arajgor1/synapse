// Synapse content script — runs on every github.com PR page.
// Inspects the page's PR body / files-changed for trace artifacts the
// Synapse audit endpoint can analyze, then injects a status badge near
// the PR title.

const BADGE_ID = "synapse-status-badge";

async function fetchAuditConfig() {
    const cfg = await chrome.storage.sync.get({
        endpoint: "https://audit.synapse.dev/api/audit",  // user-configurable in popup
        enabled: true,
    });
    return cfg;
}

function getRepoSlug() {
    // /<owner>/<repo>/pull/<n>
    const m = window.location.pathname.match(/^\/([^/]+)\/([^/]+)\/pull\/(\d+)/);
    return m ? { owner: m[1], repo: m[2], pr: m[3] } : null;
}

async function injectBadge() {
    if (document.getElementById(BADGE_ID)) return;
    const slug = getRepoSlug();
    if (!slug) return;
    const cfg = await fetchAuditConfig();
    if (!cfg.enabled) return;

    // Find a stable insertion point — GitHub's PR title bar
    const titleBar = document.querySelector('.gh-header-actions, .js-issue-title') ||
                     document.querySelector('.gh-header');
    if (!titleBar) return;

    const badge = document.createElement('a');
    badge.id = BADGE_ID;
    badge.className = 'synapse-badge synapse-loading';
    badge.href = '#';
    badge.title = 'Synapse: checking for cross-PR agent collisions…';
    badge.innerHTML = `
      <svg viewBox="0 0 16 16" width="14" height="14"><circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="2"/></svg>
      <span>Synapse</span>
    `;

    // Insert into the actions bar
    titleBar.appendChild(badge);

    // Query the audit endpoint
    try {
        const resp = await fetch(cfg.endpoint, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                owner: slug.owner, repo: slug.repo, pr: slug.pr,
            }),
        });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        renderBadge(badge, data);
    } catch (e) {
        // Endpoint unreachable — fall back to "audit available, click to run locally"
        badge.classList.remove('synapse-loading');
        badge.classList.add('synapse-unknown');
        badge.title = `Synapse: audit endpoint unreachable (${e.message}). Click to set up local audit.`;
    }
}

function renderBadge(el, data) {
    el.classList.remove('synapse-loading');
    if ((data.conflicts || 0) === 0) {
        el.classList.add('synapse-ok');
        el.title = 'Synapse: no cross-PR agent collisions detected.';
        el.innerHTML = `<svg viewBox="0 0 16 16" width="14" height="14"><path fill="currentColor" d="M13.78 4.22a.75.75 0 0 1 0 1.06l-7.25 7.25a.75.75 0 0 1-1.06 0L2.22 9.28a.75.75 0 1 1 1.06-1.06L6 10.94l6.72-6.72a.75.75 0 0 1 1.06 0z"/></svg><span>Synapse: clear</span>`;
    } else {
        el.classList.add('synapse-warn');
        el.title = `Synapse: ${data.conflicts} potential conflict(s) with other open PRs. Click for details.`;
        el.innerHTML = `<svg viewBox="0 0 16 16" width="14" height="14"><path fill="currentColor" d="M8 1.5a.75.75 0 0 1 .67.41l6.25 12.5a.75.75 0 0 1-.67 1.09H1.75a.75.75 0 0 1-.67-1.09L7.33 1.91A.75.75 0 0 1 8 1.5z"/></svg><span>Synapse: ${data.conflicts}</span>`;
        el.href = data.report_url || '#';
    }
}

// Initial inject + observe DOM mutations (GitHub uses Turbo navigation)
injectBadge();
const obs = new MutationObserver(() => injectBadge());
obs.observe(document.body, { childList: true, subtree: true });
