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
      {/* Hero */}
      <header className="mb-10">
        <div className="mb-2 flex items-baseline gap-3">
          <h1 className="text-3xl font-semibold tracking-tight">
            <span className="text-accent-blue">Synapse</span>
          </h1>
          <span className="text-xs text-muted">v0.2.8</span>
        </div>
        <p className="max-w-2xl text-sm text-text-secondary">
          Audit + coordination layer for{" "}
          <span className="text-text-primary">agentic teams that span vendors</span>.
          One Synapse session, ten different framework SDKs, one unified envelope log.
        </p>
      </header>

      {/* Latest build card — the v0.2.8 headline */}
      <section className="mb-8 rounded-lg border border-accent-blue/40 bg-gradient-to-br from-accent-blue/5 to-transparent p-5">
        <div className="mb-2 flex items-center gap-2">
          <span className="rounded bg-accent-green/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-accent-green">
            new · v0.2.8
          </span>
          <span className="text-xs text-muted">cross-framework cooperative build</span>
        </div>
        <h2 className="text-lg font-semibold text-text-primary">
          10 vendor SDKs cooperated to build a Flask Todo app — and the app actually runs.
        </h2>
        <p className="mt-1 max-w-3xl text-sm text-text-secondary">
          Ten agents from AutoGen, CrewAI, LangGraph, smolagents, Agno, LlamaIndex,
          Pydantic&nbsp;AI, OpenAI Agents SDK, Google&nbsp;ADK, and Hermes all wrote into one
          Synapse session. The produced <code className="font-mono text-accent-blue">main.py</code>{" "}
          serves <code className="font-mono">GET /todos → 200</code> locally.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Link
            href="/builds/v32"
            className="rounded bg-accent-blue/90 px-3 py-1.5 text-sm font-medium text-bg hover:bg-accent-blue"
          >
            View the v32 bundle →
          </Link>
          <span className="font-mono text-xs text-muted">
            commit{" "}
            <a
              href="https://github.com/arajgor1/synapse/commit/6340949"
              className="text-text-secondary hover:text-accent-blue"
            >
              6340949
            </a>
          </span>
        </div>
      </section>

      {/* Live sessions — keeps existing functionality */}
      <section className="rounded-lg border border-line bg-bg-panel p-5">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-text-secondary">
            Active sessions
          </h3>
          <span className="text-xs text-muted">live · refreshing every 3s</span>
        </div>

        {error && (
          <div className="rounded border border-accent-amber/40 bg-accent-amber/10 p-3 text-sm text-accent-amber">
            Gateway unreachable: {error}
            <p className="mt-1 text-xs text-text-secondary">
              Live sessions require the Synapse gateway. Start it with{" "}
              <code className="font-mono">
                uvicorn runtime.gateway.server:app --port 8000
              </code>
              . The v32 cooperative-build view above works without the gateway.
            </p>
          </div>
        )}

        {!error && sessions.length === 0 && (
          <p className="text-sm text-muted">
            No live sessions. Run a demo (e.g.{" "}
            <code className="font-mono text-text-secondary">
              python examples/two_agents_conflict_demo.py
            </code>
            ) and it'll appear here.
          </p>
        )}

        {sessions.length > 0 && (
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
        )}
      </section>

      <footer className="mt-10 flex flex-wrap items-center gap-3 text-xs text-muted">
        <a
          href="https://github.com/arajgor1/synapse"
          className="text-accent-blue hover:underline"
        >
          arajgor1/synapse
        </a>
        <span>·</span>
        <a
          href="https://github.com/arajgor1/synapse/tree/main/spec"
          className="text-accent-blue hover:underline"
        >
          protocol spec
        </a>
        <span>·</span>
        <a
          href="https://github.com/arajgor1/synapse/blob/main/bench/PUBLIC_BENCHMARK.md"
          className="text-accent-blue hover:underline"
        >
          public benchmark
        </a>
      </footer>
    </main>
  );
}
