"use client";

import type { Belief } from "@/lib/types";

export function BeliefPanel({ beliefs }: { beliefs: Map<string, Belief[]> }) {
  const keys = Array.from(beliefs.keys()).sort();
  const divergent = keys.filter((k) => isDivergent(beliefs.get(k) || []));
  const aligned = keys.filter((k) => !isDivergent(beliefs.get(k) || []));

  if (keys.length === 0) {
    return null;
  }

  return (
    <div className="rounded-lg border border-line bg-bg-panel">
      <div className="border-b border-line px-3 py-2 text-xs font-semibold text-text-secondary uppercase tracking-wide flex items-center gap-2">
        <span>beliefs</span>
        {divergent.length > 0 && (
          <span className="rounded bg-accent-red/15 px-1.5 py-0.5 text-[10px] text-accent-red">
            {divergent.length} divergent
          </span>
        )}
      </div>
      <div className="divide-y divide-line">
        {[...divergent, ...aligned].map((k) => (
          <BeliefRow key={k} keyName={k} group={beliefs.get(k) || []} />
        ))}
      </div>
    </div>
  );
}

function isDivergent(group: Belief[]): boolean {
  if (group.length < 2) return false;
  const first = JSON.stringify(group[0].value);
  return group.some((b) => JSON.stringify(b.value) !== first);
}

function BeliefRow({
  keyName,
  group,
}: {
  keyName: string;
  group: Belief[];
}) {
  const divergent = isDivergent(group);
  return (
    <div
      className={`px-3 py-2 text-xs ${
        divergent ? "bg-accent-red/5" : ""
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="font-mono font-semibold text-text-primary">
          {keyName}
        </span>
        {divergent && (
          <span className="rounded bg-accent-red/15 px-1.5 py-0.5 text-[10px] text-accent-red">
            divergent
          </span>
        )}
      </div>
      <div className="mt-1 space-y-0.5">
        {group.map((b, i) => (
          <div
            key={`${b.agent_id}-${i}`}
            className="font-mono text-text-secondary truncate"
          >
            <span className="text-muted">{b.agent_id}:</span>{" "}
            <span className="text-text-primary">
              {JSON.stringify(b.value)}
            </span>{" "}
            <span className="text-muted">
              ({b.source}, c={b.confidence.toFixed(2)})
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
