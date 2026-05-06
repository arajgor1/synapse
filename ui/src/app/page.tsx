"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

interface SessionRow {
  session_id: string;
  agent_count: number;
  last_seen: string | null;
}

export default function Home() {
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await fetch("/api/gateway/sessions");
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = (await r.json()) as { sessions: SessionRow[] };
        if (!cancelled) {
          setSessions(data.sessions);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    };
    tick();
    const id = setInterval(tick, 3000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <header className="mb-8 flex items-baseline gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">
          <span className="text-accent-blue">Synapse</span>{" "}
          <span className="text-text-secondary">Observability</span>
        </h1>
        <span className="text-xs text-muted">v0.1 alpha</span>
      </header>

      <section className="rounded-lg border border-line bg-bg-panel p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wide">
            Active sessions
          </h2>
          <span className="text-xs text-muted">refreshing every 3s</span>
        </div>

        {error && (
          <div className="rounded border border-accent-red/40 bg-accent-red/10 p-3 text-sm text-accent-red">
            Gateway unreachable: {error}
            <p className="mt-1 text-xs text-text-secondary">
              Start it with{" "}
              <code className="font-mono">
                uvicorn runtime.gateway.server:app --port 8000
              </code>
            </p>
          </div>
        )}

        {!error && sessions.length === 0 && (
          <p className="text-sm text-muted">
            No sessions yet. Run a demo (e.g.{" "}
            <code className="font-mono text-text-secondary">
              python examples/two_agents_conflict_demo.py
            </code>
            ) and it'll appear here.
          </p>
        )}

        <ul className="divide-y divide-line">
          {sessions.map((s) => (
            <li key={s.session_id}>
              <Link
                href={`/sessions/${encodeURIComponent(s.session_id)}`}
                className="flex items-center justify-between py-3 hover:bg-bg-panel2 px-2 -mx-2 rounded transition"
              >
                <div className="flex items-center gap-3">
                  <span className="font-mono text-sm">{s.session_id}</span>
                  <span className="rounded bg-bg-panel2 px-2 py-0.5 text-xs text-text-secondary">
                    {s.agent_count} agent{s.agent_count === 1 ? "" : "s"}
                  </span>
                </div>
                <span className="text-xs text-muted">
                  {s.last_seen
                    ? new Date(s.last_seen).toLocaleTimeString()
                    : "—"}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <footer className="mt-8 text-xs text-muted">
        Repo:{" "}
        <a
          href="https://github.com/arajgor1/synapse"
          className="text-accent-blue hover:underline"
        >
          arajgor1/synapse
        </a>{" "}
        ·{" "}
        <a
          href="https://github.com/arajgor1/synapse/tree/main/spec"
          className="text-accent-blue hover:underline"
        >
          protocol spec
        </a>
      </footer>
    </main>
  );
}
