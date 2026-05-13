"use client";

import { BundleEnvelope } from "@/lib/bundle";

interface Props {
  envelopes: BundleEnvelope[];
}

export function EnvelopeTimeline({ envelopes }: Props) {
  if (envelopes.length === 0) {
    return (
      <section className="rounded-lg border border-line bg-bg-panel p-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
          envelope timeline
        </h3>
        <p className="mt-2 text-sm text-muted">No envelopes in this bundle.</p>
      </section>
    );
  }

  const first = envelopes[0].ts_ms;

  return (
    <section className="flex h-full flex-col rounded-lg border border-line bg-bg-panel p-4">
      <header className="mb-2 flex items-baseline justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
          envelope timeline
        </h3>
        <span className="text-[10px] text-muted">
          {envelopes.length} envelopes · {sessionDurationMs(envelopes).toFixed(0)}ms span
        </span>
      </header>

      <div className="flex-1 space-y-1 overflow-auto pr-1">
        {envelopes.map((e, i) => (
          <Row key={`${e.id ?? i}`} env={e} firstMs={first} index={i} />
        ))}
      </div>
    </section>
  );
}

function Row({
  env,
  firstMs,
  index,
}: {
  env: BundleEnvelope;
  firstMs: number;
  index: number;
}) {
  const delta = env.ts_ms - firstMs;
  const action =
    typeof env.action === "string" ? env.action : JSON.stringify(env.action);
  const truncated = action.length > 80 ? `${action.slice(0, 77)}...` : action;
  const typeColor =
    env.type === "INTENTION"
      ? "text-accent-blue"
      : env.type === "RESOLUTION"
        ? "text-accent-green"
        : env.type === "CONFLICT"
          ? "text-accent-red"
          : env.type === "THOUGHT"
            ? "text-accent-violet"
            : "text-text-secondary";

  return (
    <div className="grid grid-cols-[3rem_5rem_6rem_1fr] items-baseline gap-2 rounded border border-transparent px-2 py-1.5 font-mono text-[11px] leading-relaxed hover:border-line hover:bg-bg-panel2">
      <span className="text-muted">+{(delta / 1000).toFixed(1)}s</span>
      <span className={typeColor}>{env.type}</span>
      <span
        className="truncate text-text-secondary"
        title={`${env.agent_id} (${env.vendor_name ?? "unknown vendor"})`}
      >
        {env.badge ? (
          <span className="mr-1 inline-block rounded bg-bg-panel2 px-1 py-px text-[9px] text-muted">
            {env.badge}
          </span>
        ) : null}
        {env.agent_id}
      </span>
      <span className="truncate text-text-primary" title={action}>
        {truncated}
      </span>
    </div>
  );
}

function sessionDurationMs(envs: BundleEnvelope[]): number {
  if (envs.length < 2) return 0;
  return envs[envs.length - 1].ts_ms - envs[0].ts_ms;
}
