"use client";

import { useEffect, useMemo, useState } from "react";
import type { Envelope } from "@/lib/types";

interface ReplayScrubberProps {
  events: Array<{ entry_id: string; envelope: Envelope }>;
  /** Called with the index of the currently-visible-up-to event (inclusive),
   * or null to mean "live mode — show everything as it streams in". */
  onCursorChange: (cursorIdx: number | null) => void;
  /** True when the cursor is at the live tail (most recent event). */
  isLive: boolean;
}

export function ReplayScrubber({
  events,
  onCursorChange,
  isLive,
}: ReplayScrubberProps) {
  // Cursor: null = live, otherwise an integer index into events
  const [cursor, setCursor] = useState<number | null>(null);

  // When new events arrive AND we're in live mode, stay at the tail
  useEffect(() => {
    if (cursor === null) {
      onCursorChange(null);
    }
  }, [events.length, cursor, onCursorChange]);

  const total = events.length;
  const cursorIdx = cursor === null ? total - 1 : cursor;
  const env = events[cursorIdx]?.envelope;

  const firstTs = events[0]?.envelope.timestamp_ms;
  const lastTs = events[total - 1]?.envelope.timestamp_ms;
  const cursorTs = env?.timestamp_ms;

  const totalSeconds = useMemo(() => {
    if (!firstTs || !lastTs) return 0;
    return (lastTs - firstTs) / 1000;
  }, [firstTs, lastTs]);

  const cursorSeconds = useMemo(() => {
    if (!firstTs || !cursorTs) return 0;
    return (cursorTs - firstTs) / 1000;
  }, [firstTs, cursorTs]);

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const idx = parseInt(e.target.value, 10);
    if (idx >= total - 1) {
      setCursor(null);
      onCursorChange(null);
    } else {
      setCursor(idx);
      onCursorChange(idx);
    }
  };

  const goLive = () => {
    setCursor(null);
    onCursorChange(null);
  };

  const goBack = () => {
    const next = cursor === null ? total - 2 : Math.max(0, cursor - 1);
    setCursor(next);
    onCursorChange(next);
  };

  const goForward = () => {
    if (cursor === null) return;
    const next = cursor + 1;
    if (next >= total - 1) {
      setCursor(null);
      onCursorChange(null);
    } else {
      setCursor(next);
      onCursorChange(next);
    }
  };

  if (total === 0) {
    return (
      <div className="rounded-lg border border-line bg-bg-panel p-3 text-xs text-muted">
        Replay scrubber appears once events arrive.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-line bg-bg-panel p-3">
      <div className="flex items-center justify-between text-xs">
        <span className="font-semibold text-text-secondary uppercase tracking-wide">
          replay
        </span>
        {isLive ? (
          <span className="flex items-center gap-1 text-accent-green">
            <span className="block h-1.5 w-1.5 rounded-full bg-accent-green animate-pulse-fast" />
            live
          </span>
        ) : (
          <button
            onClick={goLive}
            className="text-accent-blue hover:underline font-mono"
          >
            jump to live →
          </button>
        )}
      </div>

      <div className="mt-2 flex items-center gap-2">
        <button
          onClick={goBack}
          className="rounded border border-line px-1.5 py-0.5 text-xs text-text-secondary hover:bg-bg-panel2"
          title="step back"
        >
          ◄
        </button>
        <input
          type="range"
          min={0}
          max={Math.max(0, total - 1)}
          value={cursorIdx}
          onChange={handleSeek}
          className="flex-1 accent-accent-blue"
        />
        <button
          onClick={goForward}
          disabled={cursor === null}
          className="rounded border border-line px-1.5 py-0.5 text-xs text-text-secondary hover:bg-bg-panel2 disabled:opacity-40 disabled:cursor-not-allowed"
          title="step forward"
        >
          ►
        </button>
      </div>

      <div className="mt-2 flex items-center justify-between text-[10px] text-muted font-mono">
        <span>
          {cursorSeconds.toFixed(1)}s / {totalSeconds.toFixed(1)}s
        </span>
        <span>
          event {cursorIdx + 1} / {total}
        </span>
      </div>

      {env && (
        <div className="mt-1.5 text-[10px] font-mono text-text-secondary truncate">
          <span className="text-muted">at cursor: </span>
          <span>{env.type}</span>{" "}
          <span className="text-text-primary">{env.agent_id}</span>
        </div>
      )}
    </div>
  );
}
