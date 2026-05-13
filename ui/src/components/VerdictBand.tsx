"use client";

import { BundleSummary } from "@/lib/bundle";

interface Props {
  summary: BundleSummary;
  session: string;
  commit: string;
}

export function VerdictBand({ summary, session, commit }: Props) {
  return (
    <section className="rounded-lg border border-line bg-bg-panel p-5">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold tracking-tight text-text-primary">
          Cross-framework cooperative build
        </h2>
        <div className="font-mono text-xs text-muted">
          session = <span className="text-text-secondary">{session}</span> ·
          commit = <span className="text-text-secondary">{commit}</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="vendors"      value={summary.vendor_count} />
        <Stat label="files"        value={summary.files_written} />
        <Stat label="intents"      value={summary.intents} />
        <AppRunsStat
          ok={summary.app_runs}
          check={summary.app_check}
        />
      </div>

      {summary.elapsed_s !== undefined && (
        <p className="mt-3 text-xs text-muted">
          {summary.vendor_count} agentic SDKs collaborated on one Synapse
          session and produced a Flask Todo app in{" "}
          <span className="font-mono text-text-secondary">
            {summary.elapsed_s.toFixed(1)}s
          </span>{" "}
          (Modal sandbox).
        </p>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border border-line bg-bg-panel2 p-3">
      <div className="text-[10px] uppercase tracking-wide text-muted">
        {label}
      </div>
      <div className="mt-1 font-mono text-2xl font-semibold text-text-primary">
        {value}
      </div>
    </div>
  );
}

function AppRunsStat({ ok, check }: { ok: boolean; check: string }) {
  return (
    <div
      className={`rounded border p-3 ${
        ok
          ? "border-accent-green/40 bg-accent-green/10"
          : "border-accent-red/40 bg-accent-red/10"
      }`}
    >
      <div className="text-[10px] uppercase tracking-wide text-muted">
        app runs
      </div>
      <div
        className={`mt-1 font-mono text-2xl font-semibold ${
          ok ? "text-accent-green" : "text-accent-red"
        }`}
      >
        {ok ? "✓ yes" : "✗ no"}
      </div>
      <div className="mt-1 truncate text-[11px] text-text-secondary" title={check}>
        {check}
      </div>
    </div>
  );
}
