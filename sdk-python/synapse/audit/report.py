"""HTML + JSON report generator for audit results.

The HTML report is intentionally self-contained (no external CSS/JS) so
it can be opened in any browser, attached to email, or pasted into a
GitHub PR description as a screenshot.
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .events import AuditEvent
from .conflict_detector import AuditConflict


@dataclass
class AuditReport:
    """Result of running the audit pipeline."""

    source_path: str
    total_events: int
    total_write_events: int
    sessions: dict[str, list[str]]  # session_id -> list of agent_ids seen
    conflicts: list[AuditConflict]

    # Cost-of-collision estimates
    estimated_wasted_tokens: int = 0
    estimated_wasted_usd: float = 0.0

    @property
    def total_conflicts(self) -> int:
        return len(self.conflicts)

    @property
    def conflict_kinds(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.conflicts:
            out[c.kind] = out.get(c.kind, 0) + 1
        return out

    def to_json_dict(self) -> dict:
        return {
            "source": self.source_path,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_events": self.total_events,
            "total_write_events": self.total_write_events,
            "total_sessions": len(self.sessions),
            "total_conflicts": self.total_conflicts,
            "conflict_kinds": self.conflict_kinds,
            "estimated_wasted_tokens": self.estimated_wasted_tokens,
            "estimated_wasted_usd": round(self.estimated_wasted_usd, 4),
            "sessions": {sid: sorted(set(agents)) for sid, agents in self.sessions.items()},
            "conflicts": [c.to_dict() for c in self.conflicts],
        }

    def write_json(self, path: str) -> None:
        Path(path).write_text(json.dumps(self.to_json_dict(), indent=2), encoding="utf-8")

    def write_html(self, path: str) -> None:
        Path(path).write_text(_render_html(self), encoding="utf-8")

    def print_summary(self) -> None:
        kinds = self.conflict_kinds
        kind_str = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())) or "none"
        print(f"Loaded {self.total_events} events from {len(self.sessions)} session(s).")
        print(f"  write events:   {self.total_write_events}")
        print(f"  conflicts:      {self.total_conflicts} ({kind_str})")
        if self.estimated_wasted_tokens:
            print(
                f"  est. waste:     ~{self.estimated_wasted_tokens:,} tokens "
                f"/ ~${self.estimated_wasted_usd:.2f}"
            )


def _render_html(report: AuditReport) -> str:
    rows = []
    for c in report.conflicts:
        ts = datetime.fromtimestamp(c.intention.ts_start_ms / 1000, tz=timezone.utc)
        kind_class = "kind-active" if c.kind == "scope_overlap" else "kind-stale"
        kind_label = "ACTIVE OVERLAP" if c.kind == "scope_overlap" else "STALE-BASE OVERWRITE"
        others = ", ".join(html.escape(o.agent_id) for o in c.conflicting)
        scopes = ", ".join(f"<code>{html.escape(s)}</code>" for s in c.overlapping_scopes)
        rows.append(f"""
        <tr>
          <td class="ts">{ts.isoformat()}</td>
          <td class="agent">{html.escape(c.intention.agent_id)}</td>
          <td><code>{html.escape(c.intention.tool_name)}</code></td>
          <td>{scopes}</td>
          <td class="agent">vs {others}</td>
          <td class="{kind_class}">{kind_label}</td>
          <td class="rationale">{html.escape(c.rationale)}</td>
        </tr>""")

    sessions_html = ""
    for sid, agents in sorted(report.sessions.items()):
        agents_str = ", ".join(f"<code>{html.escape(a)}</code>" for a in sorted(set(agents)))
        sessions_html += (
            f"<li><code>{html.escape(sid)}</code> — {len(set(agents))} agent(s): {agents_str}</li>"
        )

    kind_summary = report.conflict_kinds
    waste_line = ""
    if report.estimated_wasted_tokens:
        waste_line = (
            f'<div class="metric"><span class="metric-num">'
            f"~${report.estimated_wasted_usd:.2f}</span>"
            f"<span class=metric-label>est. wasted (~{report.estimated_wasted_tokens:,} tok)</span></div>"
        )

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8" />
<title>Synapse Audit — {html.escape(report.source_path)}</title>
<style>
  :root {{
    --bg:#0e1116; --fg:#e6edf3; --muted:#7a838e; --border:#272d36;
    --accent:#ff8c42; --warn:#f6c453; --bad:#e0533d; --ok:#52d273;
  }}
  body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,Segoe UI,system-ui,sans-serif}}
  header{{padding:24px 32px;border-bottom:1px solid var(--border)}}
  h1{{margin:0;font-size:22px;font-weight:600}}
  h1 small{{display:block;font-size:12px;color:var(--muted);margin-top:4px;font-weight:400}}
  main{{padding:24px 32px;max-width:1200px;margin:0 auto}}
  .metrics{{display:flex;gap:24px;margin:24px 0 32px;flex-wrap:wrap}}
  .metric{{flex:1;min-width:180px;background:#161b22;border:1px solid var(--border);
          border-radius:8px;padding:16px}}
  .metric-num{{display:block;font-size:32px;font-weight:600;color:var(--accent)}}
  .metric-label{{display:block;color:var(--muted);font-size:12px;margin-top:4px}}
  table{{width:100%;border-collapse:collapse;margin:16px 0;font-size:13px}}
  th,td{{padding:10px 12px;text-align:left;vertical-align:top;border-bottom:1px solid var(--border)}}
  th{{color:var(--muted);font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:.5px}}
  td.ts{{font-family:Menlo,Consolas,monospace;color:var(--muted);font-size:12px;white-space:nowrap}}
  td.agent code{{color:var(--accent)}}
  td.kind-active{{color:var(--bad);font-weight:600;font-size:11px}}
  td.kind-stale{{color:var(--warn);font-weight:600;font-size:11px}}
  td.rationale{{color:var(--muted);font-size:12px;max-width:320px}}
  code{{font-family:Menlo,Consolas,monospace;font-size:12px;background:#161b22;
        padding:2px 6px;border-radius:3px}}
  ul{{padding-left:20px;color:var(--muted)}}
  ul li{{margin-bottom:4px}}
  h2{{font-size:16px;font-weight:600;margin-top:32px;color:var(--fg)}}
  .empty{{padding:24px;text-align:center;color:var(--muted);
         border:1px dashed var(--border);border-radius:8px}}
  footer{{padding:16px 32px;color:var(--muted);font-size:11px;border-top:1px solid var(--border);text-align:center}}
</style>
</head><body>
<header>
  <h1>Synapse Audit
    <small>{html.escape(report.source_path)} · generated {datetime.now(timezone.utc).isoformat()}</small>
  </h1>
</header>
<main>

<div class="metrics">
  <div class="metric">
    <span class="metric-num">{report.total_events}</span>
    <span class="metric-label">tool calls observed</span>
  </div>
  <div class="metric">
    <span class="metric-num">{report.total_write_events}</span>
    <span class="metric-label">write-class operations</span>
  </div>
  <div class="metric">
    <span class="metric-num">{len(report.sessions)}</span>
    <span class="metric-label">multi-agent sessions</span>
  </div>
  <div class="metric">
    <span class="metric-num" style="color:{'var(--bad)' if report.total_conflicts else 'var(--ok)'}">
      {report.total_conflicts}
    </span>
    <span class="metric-label">silent conflicts found</span>
  </div>
  {waste_line}
</div>

<h2>Conflict breakdown</h2>
{
  "<ul>" + "".join(f"<li><b>{k}</b>: {v}</li>" for k,v in sorted(kind_summary.items())) + "</ul>"
  if kind_summary
  else '<div class="empty">No conflicts detected. Either your agents are well-coordinated, or scope inference missed something.</div>'
}

<h2>Sessions seen</h2>
<ul>{sessions_html or "<li>None</li>"}</ul>

<h2>All conflicts ({report.total_conflicts})</h2>
{
  '<table><thead><tr><th>When</th><th>Agent</th><th>Tool</th><th>Scope</th><th>Collided with</th><th>Kind</th><th>Why it matters</th></tr></thead><tbody>'
  + "".join(rows) + '</tbody></table>'
  if rows
  else '<div class="empty">No conflicts.</div>'
}

</main>
<footer>Synapse Audit · <code>synapse audit</code> · github.com/arajgor1/synapse</footer>
</body></html>
"""
