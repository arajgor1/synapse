"use client";

import { BundleRole } from "@/lib/bundle";
import { VENDORS } from "@/lib/vendors";

interface Props {
  roles: BundleRole[];
  selected: string | null;
  onSelect: (file: string) => void;
}

export function VendorAgentGrid({ roles, selected, onSelect }: Props) {
  return (
    <section className="rounded-lg border border-line bg-bg-panel p-4">
      <header className="mb-3 flex items-baseline justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
          10 cross-vendor agents
        </h3>
        <span className="text-[10px] text-muted">click a card to preview the file it produced</span>
      </header>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-2 xl:grid-cols-2">
        {roles.map((r) => {
          const v = VENDORS[r.framework];
          const isSelected = selected === r.file;
          return (
            <button
              key={r.framework}
              type="button"
              onClick={() => onSelect(r.file)}
              className={`flex items-start gap-3 rounded border p-3 text-left transition ${
                isSelected
                  ? "border-accent-blue bg-accent-blue/10"
                  : "border-line bg-bg-panel2 hover:border-text-secondary"
              }`}
            >
              <div
                className={`flex h-9 w-9 flex-none items-center justify-center rounded font-mono text-[11px] font-semibold ${
                  v?.hue ?? "text-text-primary"
                } bg-bg-panel`}
                title={v?.vendor ?? ""}
              >
                {v?.badge ?? "??"}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-sm font-semibold text-text-primary">
                    {v?.name ?? r.framework}
                  </span>
                  {r.via_fallback ? (
                    <span
                      className="rounded bg-accent-violet/15 px-1.5 py-0.5 font-mono text-[9px] uppercase text-accent-violet"
                      title={r.reason ?? "fallback used"}
                    >
                      fallback
                    </span>
                  ) : (
                    <span className="rounded bg-accent-green/10 px-1.5 py-0.5 font-mono text-[9px] uppercase text-accent-green">
                      direct
                    </span>
                  )}
                </div>
                <div className="text-[11px] text-text-secondary">{r.role}</div>
                <div className="mt-1 flex items-baseline gap-2">
                  <code className="font-mono text-[11px] text-accent-blue">
                    {r.file}
                  </code>
                  <span className="text-[10px] text-muted">
                    {r.bytes}B
                  </span>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}
