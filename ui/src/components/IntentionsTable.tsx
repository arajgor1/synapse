"use client";

import type { Intention } from "@/lib/types";

interface IntentionsTableProps {
  intentions: Intention[];
  conflictCount: Map<string, number>;
}

const statusBadge: Record<Intention["status"], string> = {
  pending: "bg-bg-panel2 text-text-secondary",
  active: "bg-accent-blue/15 text-accent-blue",
  resolved: "bg-accent-green/15 text-accent-green",
  pivoted: "bg-accent-amber/15 text-accent-amber",
};

export function IntentionsTable({
  intentions,
  conflictCount,
}: IntentionsTableProps) {
  // Newest first, capped at 50 for the panel
  const sorted = [...intentions]
    .sort((a, b) => {
      const at = a.created_at ? new Date(a.created_at).getTime() : 0;
      const bt = b.created_at ? new Date(b.created_at).getTime() : 0;
      return bt - at;
    })
    .slice(0, 50);

  return (
    <div className="rounded-lg border border-line bg-bg-panel">
      <div className="border-b border-line px-3 py-2 text-xs font-semibold text-text-secondary uppercase tracking-wide">
        intentions
      </div>
      {sorted.length === 0 ? (
        <div className="px-3 py-6 text-center text-sm text-muted">
          No intentions yet.
        </div>
      ) : (
        <div className="divide-y divide-line">
          {sorted.map((it) => {
            const conflicts = conflictCount.get(it.id) || 0;
            return (
              <div
                key={it.id}
                className={`px-3 py-2 text-xs ${
                  conflicts > 0 ? "bg-accent-red/5" : ""
                }`}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${
                      statusBadge[it.status]
                    }`}
                  >
                    {it.status}
                  </span>
                  <span className="font-mono text-text-secondary">
                    {it.agent_id}
                  </span>
                  <span className="font-mono text-text-primary">
                    [{it.scope.join(", ")}]
                  </span>
                  {it.blocking && (
                    <span className="rounded bg-accent-amber/10 px-1 text-[10px] text-accent-amber">
                      blocking
                    </span>
                  )}
                  {conflicts > 0 && (
                    <span className="ml-auto rounded bg-accent-red/15 px-1.5 py-0.5 text-[10px] text-accent-red">
                      {conflicts} conflict{conflicts === 1 ? "" : "s"}
                    </span>
                  )}
                </div>
                {it.expected_outcome && (
                  <div className="mt-1 text-text-secondary truncate">
                    {it.expected_outcome}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
