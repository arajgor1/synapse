"""``synapse watch`` — one-shot live coordination dashboard.

What it does
------------
Every other Synapse onboarding path makes the user think (which env vars,
which Redis URL, which port). ``synapse watch`` collapses that to:

    pip install synapse-protocol
    synapse watch

…and a browser tab pops open showing live INTENTION / CONFLICT events
streaming from any agent code in the user's repo.

Operations
~~~~~~~~~~
1. Engages **zero-infra mode** if the user has no Redis/Postgres set up.
   ``synapse.intend()`` calls in their app land in SQLite at
   ``~/.synapse/state.db`` and emit through the in-memory bus.
2. Tails the JSONL audit log at ``./.synapse/runs/<session>.jsonl``
   (creating the directory if missing) — that's the file the streaming
   server watches.
3. Starts the WebSocket streaming server on ``--port`` (default 8765)
   in a background thread. Pushes every appended event live to any
   connected dashboard.
4. Serves a tiny static HTML dashboard on ``--http-port`` (default 8766)
   that connects to the WS server and renders events.
5. Opens the dashboard URL in the user's default browser via
   ``webbrowser.open()``.

Use ``--no-browser`` to skip the auto-open (useful for headless / CI).
Use ``--once`` to exit after N seconds of inactivity (smoke testing).

Limitations
~~~~~~~~~~~
This is **single-process** by design (the in-memory bus doesn't span
processes). If your agent code runs in a separate Python process from
``synapse watch``, you need the live mode (Redis URL set in both procs).
The CLI prints a clear note about this on startup.
"""
from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

logger = logging.getLogger(__name__)


_DASHBOARD_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>synapse watch</title>
<style>
  body { font-family: -apple-system, system-ui, "Segoe UI", monospace;
         background: #0b0c10; color: #e8e8e8; margin: 0; padding: 16px; }
  h1   { font-size: 18px; margin: 0 0 12px 0; color: #66d9ef; }
  .stat { display: inline-block; margin-right: 20px; padding: 8px 14px;
          background: #1a1d24; border-radius: 6px; }
  .num { font-size: 22px; font-weight: 600; color: #66d9ef; }
  .lbl { font-size: 11px; text-transform: uppercase; color: #9aa1ac;
         margin-top: 2px; letter-spacing: 0.06em; }
  table { width: 100%; margin-top: 16px; border-collapse: collapse;
          background: #14171c; }
  th { text-align: left; padding: 8px 10px; font-size: 11px;
       text-transform: uppercase; color: #9aa1ac; border-bottom: 1px solid #2a2e36; }
  td { padding: 8px 10px; font-size: 12.5px; border-bottom: 1px solid #1f232a;
       vertical-align: top; }
  tr.conflict td { background: rgba(239, 68, 68, 0.08); }
  tr.conflict td:first-child { border-left: 2px solid #ef4444; }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 999px;
          font-size: 11px; background: #1f232a; color: #c9d1d9; }
  .pill.conflict { background: #ef4444; color: white; }
  .scope { color: #66d9ef; font-family: ui-monospace, monospace; }
  .conn { float: right; padding: 4px 10px; border-radius: 4px;
          background: #1a1d24; font-size: 11px; }
  .conn.ok { background: #16a34a; color: white; }
  .conn.bad { background: #ef4444; color: white; }
  code { background: #14171c; padding: 1px 4px; border-radius: 3px; }
</style></head><body>
<h1>synapse watch <span class="conn" id="conn">connecting…</span></h1>
<div>
  <div class="stat"><div class="num" id="n_events">0</div><div class="lbl">events</div></div>
  <div class="stat"><div class="num" id="n_conflicts">0</div><div class="lbl">conflicts</div></div>
  <div class="stat"><div class="num" id="n_agents">0</div><div class="lbl">agents</div></div>
</div>
<table id="t">
  <thead><tr><th>type</th><th>agent</th><th>tool / kind</th><th>scope</th><th>time</th></tr></thead>
  <tbody></tbody>
</table>
<script>
  const wsUrl = "ws://" + location.hostname + ":__WS_PORT__/";
  const tbody = document.querySelector("#t tbody");
  const conn = document.getElementById("conn");
  let n_events = 0, n_conflicts = 0;
  const agents = new Set();
  function fmtTs(ms) { return ms ? new Date(ms).toLocaleTimeString() : "—"; }
  function escHtml(s){ return String(s==null?'':s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
  function renderRow(msg) {
    const tr = document.createElement("tr");
    if (msg.type === "conflict") tr.className = "conflict";
    const pillCls = msg.type === "conflict" ? "pill conflict" : "pill";
    const tool = msg.type === "conflict"
      ? (msg.kind || "scope_overlap")
      : (msg.tool_name || "—");
    const agent = msg.type === "conflict"
      ? (msg.intention_agent || "?")
      : (msg.agent_id || "?");
    const scope = (msg.scopes || (msg.tool_args && msg.tool_args.scope) || []).join(", ");
    tr.innerHTML =
      `<td><span class="${pillCls}">${escHtml(msg.type)}</span></td>` +
      `<td>${escHtml(agent)}</td>` +
      `<td>${escHtml(tool)}</td>` +
      `<td class="scope">${escHtml(scope || "—")}</td>` +
      `<td>${escHtml(fmtTs(msg.ts_ms))}</td>`;
    tbody.insertBefore(tr, tbody.firstChild);
    while (tbody.children.length > 200) tbody.removeChild(tbody.lastChild);
    if (msg.type === "event") { n_events++; if (msg.agent_id) agents.add(msg.agent_id); }
    if (msg.type === "conflict") n_conflicts++;
    document.getElementById("n_events").textContent = n_events;
    document.getElementById("n_conflicts").textContent = n_conflicts;
    document.getElementById("n_agents").textContent = agents.size;
  }
  function connect() {
    const ws = new WebSocket(wsUrl);
    ws.onopen = () => { conn.textContent = "live"; conn.className = "conn ok"; };
    ws.onclose = () => { conn.textContent = "disconnected"; conn.className = "conn bad";
                          setTimeout(connect, 1000); };
    ws.onerror = () => { conn.className = "conn bad"; };
    ws.onmessage = (e) => {
      try { renderRow(JSON.parse(e.data)); } catch (_) {}
    };
  }
  connect();
</script>
</body></html>
"""


def _free_port(start: int = 8765) -> int:
    """Find a free TCP port at or after ``start``."""
    port = start
    while port < start + 50:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("0.0.0.0", port))
            s.close()
            return port
        except OSError:
            port += 1
        finally:
            try:
                s.close()
            except Exception:
                pass
    raise RuntimeError(f"No free port found in {start}-{port}")


def _make_dashboard_handler(html_bytes: bytes):
    class _Handler(BaseHTTPRequestHandler):
        # Silence per-request stderr logging — too noisy for CLI.
        def log_message(self, format, *args):
            return

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html_bytes)))
                self.end_headers()
                self.wfile.write(html_bytes)
            else:
                self.send_response(404)
                self.end_headers()

    return _Handler


def cmd_watch(args: argparse.Namespace) -> int:
    # Deferred imports — keeps `synapse audit` cold-start cheap
    from synapse.streaming.server import StreamingServer

    runs_dir = Path(args.runs_dir).resolve()
    runs_dir.mkdir(parents=True, exist_ok=True)
    log_path = runs_dir / f"{args.session}.jsonl"
    if not log_path.exists():
        log_path.touch()

    # Force zero-infra unless user explicitly set Redis URL.
    if not os.environ.get("SYNAPSE_REDIS_URL"):
        os.environ.pop("SYNAPSE_OFFLINE", None)
    # Make every intend() call append to the file the streaming server
    # is tailing. We do this via the standard JSONL audit logger that
    # the SDK already supports.
    os.environ.setdefault("SYNAPSE_AUDIT_LOG", str(log_path))
    os.environ.setdefault("SYNAPSE_SESSION_ID", args.session)

    ws_port = _free_port(args.port)
    http_port = _free_port(args.http_port)

    # Streaming server (background thread)
    streaming = StreamingServer(ws_port, log_path)
    ws_thread = threading.Thread(
        target=streaming.serve_forever, daemon=True, name="synapse-watch-ws"
    )
    ws_thread.start()

    # Static HTML dashboard server (background thread)
    html_bytes = _DASHBOARD_HTML.replace("__WS_PORT__", str(ws_port)).encode("utf-8")
    httpd = HTTPServer(("0.0.0.0", http_port), _make_dashboard_handler(html_bytes))
    http_thread = threading.Thread(
        target=httpd.serve_forever, daemon=True, name="synapse-watch-http"
    )
    http_thread.start()

    dashboard_url = f"http://localhost:{http_port}/"
    # ASCII-only banner — Windows cp1252 console can't render unicode
    # box-drawing chars and would crash the print() call.
    print("", flush=True)
    print("  synapse watch -- live coordination dashboard", flush=True)
    print("  " + "-" * 44, flush=True)
    print(f"  session     : {args.session}", flush=True)
    print(f"  audit log   : {log_path}", flush=True)
    print(f"  websocket   : ws://localhost:{ws_port}/", flush=True)
    print(f"  dashboard   : {dashboard_url}", flush=True)
    mode_str = (
        "live (Redis URL set)" if os.environ.get("SYNAPSE_REDIS_URL")
        else "zero-infra (in-memory bus + SQLite)"
    )
    print(f"  mode        : {mode_str}", flush=True)
    print("", flush=True)
    print("  In this terminal OR a second terminal in the same project tree:", flush=True)
    print(f"      SYNAPSE_SESSION_ID={args.session} python your_agent_script.py", flush=True)
    print("  intend() calls will auto-discover the audit log via the project", flush=True)
    print("  root's .synapse/runs/ directory. Ctrl-C to stop.", flush=True)

    if not args.no_browser:
        try:
            webbrowser.open(dashboard_url)
        except Exception:
            pass

    if args.once:
        # Smoke-test mode: wait briefly and exit cleanly.
        time.sleep(args.once)
        streaming._stop.set()
        httpd.shutdown()
        return 0

    try:
        # Block forever in the main thread (CTRL-C aware).
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n  shutting down…", flush=True)
        streaming._stop.set()
        httpd.shutdown()
        return 0


def add_subparser(sub: argparse._SubParsersAction) -> None:
    """Wire `synapse watch` into the main CLI subparsers."""
    p = sub.add_parser(
        "watch",
        help=(
            "Start the live coordination dashboard. Auto-engages zero-infra "
            "mode (no Redis/Postgres needed) and opens a browser tab."
        ),
    )
    p.add_argument(
        "--session", default="default",
        help="Session ID to watch (default: 'default'). "
        "Your agent code must use SYNAPSE_SESSION_ID=<this value> "
        "or pass session=<this value> to synapse.intend().",
    )
    p.add_argument(
        "--port", type=int, default=8765,
        help="WebSocket port (default 8765, auto-bumped if in use)",
    )
    p.add_argument(
        "--http-port", type=int, default=8766,
        help="Dashboard HTTP port (default 8766, auto-bumped if in use)",
    )
    p.add_argument(
        "--runs-dir", default=".synapse/runs",
        help="Directory holding the JSONL audit log (default: .synapse/runs)",
    )
    p.add_argument(
        "--no-browser", action="store_true",
        help="Don't auto-open the dashboard in the browser (useful for CI)",
    )
    p.add_argument(
        "--once", type=float, default=None, metavar="SECONDS",
        help="Run for N seconds then exit (smoke-test mode)",
    )
    p.set_defaults(func=cmd_watch)
