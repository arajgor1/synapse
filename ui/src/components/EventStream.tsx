"use client";

import { useEffect, useRef, useState } from "react";
import type { Envelope, MessageType } from "@/lib/types";

interface EventStreamProps {
  events: Array<{ entry_id: string; envelope: Envelope }>;
}

const typeColor: Record<MessageType, string> = {
  THOUGHT: "text-text-secondary",
  INTENTION: "text-accent-blue",
  PIVOT: "text-accent-amber",
  BELIEF: "text-text-secondary",
  BLOCK: "text-accent-amber",
  CONFLICT: "text-accent-red",
  RESOLUTION: "text-accent-green",
  COST_REPORT: "text-muted",
};

const TYPES: MessageType[] = [
  "INTENTION",
  "CONFLICT",
  "RESOLUTION",
  "PIVOT",
  "BELIEF",
  "BLOCK",
  "THOUGHT",
  "COST_REPORT",
];

export function EventStream({ events }: EventStreamProps) {
  const [filter, setFilter] = useState<Set<MessageType>>(
    new Set(TYPES.filter((t) => t !== "THOUGHT" && t !== "COST_REPORT")),
  );
  const [autoscroll, setAutoscroll] = useState(true);
  const ref = useRef<HTMLDivElement>(null);

  const filtered = events.filter((e) => filter.has(e.envelope.type));

  useEffect(() => {
    if (!autoscroll) return;
    if (ref.current) {
      ref.current.scrollTop = ref.current.scrollHeight;
    }
  }, [filtered.length, autoscroll]);

  const toggle = (t: MessageType) => {
    const next = new Set(filter);
    if (next.has(t)) next.delete(t);
    else next.add(t);
    setFilter(next);
  };

  return (
    <div className="flex flex-col h-full rounded-lg border border-line bg-bg-panel">
      <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
        <span className="text-xs font-semibold text-text-secondary uppercase tracking-wide mr-2">
          events
        </span>
        {TYPES.map((t) => (
          <button
            key={t}
            onClick={() => toggle(t)}
            className={`rounded border px-2 py-0.5 text-[10px] font-mono transition ${
              filter.has(t)
                ? "border-line bg-bg-panel2 text-text-primary"
                : "border-line bg-transparent text-muted hover:text-text-secondary"
            }`}
          >
            {t}
          </button>
        ))}
        <label className="ml-auto flex items-center gap-1 text-xs text-text-secondary cursor-pointer">
          <input
            type="checkbox"
            checked={autoscroll}
            onChange={(e) => setAutoscroll(e.target.checked)}
            className="accent-accent-blue"
          />
          autoscroll
        </label>
      </div>

      <div ref={ref} className="flex-1 overflow-y-auto px-3 py-2 font-mono text-xs">
        {filtered.length === 0 ? (
          <div className="text-muted py-8 text-center">No events yet.</div>
        ) : (
          filtered.map(({ entry_id, envelope }) => (
            <EventRow key={entry_id} envelope={envelope} />
          ))
        )}
      </div>
    </div>
  );
}

function EventRow({ envelope }: { envelope: Envelope }) {
  const ts = new Date(envelope.timestamp_ms);
  const time = ts.toLocaleTimeString(undefined, {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  return (
    <div className="flex gap-2 py-0.5 hover:bg-bg-panel2 px-1 -mx-1 rounded">
      <span className="text-muted shrink-0 tabular-nums">{time}</span>
      <span
        className={`shrink-0 ${typeColor[envelope.type]} font-semibold w-[7.5em]`}
      >
        {envelope.type}
      </span>
      <span className="text-text-secondary shrink-0 truncate max-w-[10em]">
        {envelope.agent_id}
      </span>
      <span className="text-text-primary truncate flex-1">
        {summarize(envelope)}
      </span>
    </div>
  );
}

function summarize(env: Envelope): string {
  const p = env.payload;
  switch (env.type) {
    case "INTENTION": {
      const scope = (p.scope as string[] | undefined) || [];
      return `scope=[${scope.join(", ")}]  ${
        (p.expected_outcome as string) || ""
      }`;
    }
    case "CONFLICT": {
      const overlap = (p.overlapping_scopes as string[] | undefined) || [];
      return `kind=${p.kind} overlap=[${overlap.join(", ")}] suggest=${
        p.suggested_resolution || "—"
      }`;
    }
    case "RESOLUTION": {
      return `${p.outcome || "—"} (intention=${(p.intention_id as string)?.slice(0, 8) ?? "?"}…)`;
    }
    case "PIVOT": {
      return `${p.reason || ""}`;
    }
    case "BELIEF": {
      return `${p.key}=${JSON.stringify(p.value)} (${p.source}, c=${p.confidence})`;
    }
    case "BLOCK": {
      return `${p.blocker || ""}`;
    }
    case "THOUGHT": {
      return `${(p.summary as string)?.slice(0, 200) || ""}`;
    }
    case "COST_REPORT": {
      return `tokens=${p.tokens_billed} ms=${p.wall_clock_ms} usd=${
        typeof p.estimated_usd === "number" ? p.estimated_usd.toFixed(5) : "—"
      }`;
    }
    default:
      return JSON.stringify(p).slice(0, 200);
  }
}
