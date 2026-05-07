"use client";

import { useMemo } from "react";
import type { Envelope } from "@/lib/types";

interface CostChartProps {
  events: Array<{ entry_id: string; envelope: Envelope }>;
  totalUsd: number;
}

interface Point {
  t: number; // ms since first event
  cumulative: number; // USD
}

const WIDTH = 320;
const HEIGHT = 80;

export function CostChart({ events, totalUsd }: CostChartProps) {
  const points: Point[] = useMemo(() => {
    const cost = events.filter((e) => e.envelope.type === "COST_REPORT");
    if (cost.length === 0) return [];
    const first = cost[0].envelope.timestamp_ms;
    let cum = 0;
    return cost.map((e) => {
      const usd = Number(e.envelope.payload?.estimated_usd ?? 0);
      cum += usd;
      return { t: e.envelope.timestamp_ms - first, cumulative: cum };
    });
  }, [events]);

  const last = points[points.length - 1];
  const maxT = last?.t || 1;
  const maxY = (last?.cumulative || 0.0001) * 1.05;

  const path =
    points.length > 0
      ? "M " +
        points
          .map(
            (p) =>
              `${(p.t / maxT) * (WIDTH - 4) + 2} ${
                HEIGHT - 4 - (p.cumulative / maxY) * (HEIGHT - 8)
              }`,
          )
          .join(" L ")
      : "";

  return (
    <div className="rounded-lg border border-line bg-bg-panel p-3">
      <div className="flex items-center justify-between text-xs">
        <span className="font-semibold text-text-secondary uppercase tracking-wide">
          cost over time
        </span>
        <span className="font-mono text-text-primary">
          ${totalUsd.toFixed(4)}
        </span>
      </div>
      <div className="mt-2">
        {points.length === 0 ? (
          <div className="h-[80px] flex items-center justify-center text-xs text-muted">
            No cost reports yet
          </div>
        ) : (
          <svg
            width={WIDTH}
            height={HEIGHT}
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            className="w-full h-auto"
          >
            <defs>
              <linearGradient id="costFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#5b8fff" stopOpacity="0.4" />
                <stop offset="100%" stopColor="#5b8fff" stopOpacity="0.05" />
              </linearGradient>
            </defs>
            {/* Filled area */}
            <path
              d={`${path} L ${WIDTH - 2} ${HEIGHT - 4} L 2 ${HEIGHT - 4} Z`}
              fill="url(#costFill)"
              stroke="none"
            />
            {/* Line */}
            <path
              d={path}
              fill="none"
              stroke="#5b8fff"
              strokeWidth="1.5"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            {/* End-point dot */}
            {last && (
              <circle
                cx={(last.t / maxT) * (WIDTH - 4) + 2}
                cy={HEIGHT - 4 - (last.cumulative / maxY) * (HEIGHT - 8)}
                r="3"
                fill="#5b8fff"
              />
            )}
          </svg>
        )}
      </div>
      <div className="mt-1 flex items-center justify-between text-[10px] text-muted">
        <span>{points.length} cost report{points.length === 1 ? "" : "s"}</span>
        {last && <span>{(last.t / 1000).toFixed(1)}s elapsed</span>}
      </div>
    </div>
  );
}
