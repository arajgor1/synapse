"use client";

import Link from "next/link";
import { use, useMemo, useState } from "react";
import { useSession } from "@/lib/useSession";
import { AgentGrid } from "@/components/AgentGrid";
import { EventStream } from "@/components/EventStream";
import { IntentionsTable } from "@/components/IntentionsTable";
import { BeliefPanel } from "@/components/BeliefPanel";
import { CostChart } from "@/components/CostChart";
import { ReplayScrubber } from "@/components/ReplayScrubber";

export default function SessionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const sessionId = decodeURIComponent(id);
  const session = useSession(sessionId);

  // Replay cursor: null = live; integer = show events[0..cursor] only
  const [cursor, setCursor] = useState<number | null>(null);
  const isLive = cursor === null;

  // Slice events at the cursor for downstream components
  const visibleEvents = useMemo(() => {
    if (cursor === null) return session.events;
    return session.events.slice(0, cursor + 1);
  }, [session.events, cursor]);

  // For replay mode, we recompute intentions/beliefs/conflicts from the
  // visible event slice. For live mode, we use the live state directly.
  const replayState = useMemo(() => {
    if (cursor === null) {
      return {
        intentions: Array.from(session.intentions.values()),
        beliefs: session.beliefs,
        conflictsByIntention: session.conflictsByIntention,
        costUsd: session.costUsd,
      };
    }
    // Reconstruct from visibleEvents
    const intentionMap = new Map<
      string,
      ReturnType<typeof session.intentions.get>
    >();
    const beliefs = new Map<string, Array<unknown>>() as typeof session.beliefs;
    const conflicts = new Map<string, number>();
    let costUsd = 0;
    for (const { envelope } of visibleEvents) {
      const env = envelope;
      if (env.type === "INTENTION") {
        const p = env.payload as Record<string, unknown>;
        intentionMap.set(env.msg_id, {
          id: env.msg_id,
          agent_id: env.agent_id,
          scope: (p.scope as string[]) || [],
          action: (p.action as never) || {},
          expected_outcome: (p.expected_outcome as string) || "",
          blocking: !!p.blocking,
          status: "active",
          created_at: new Date(env.timestamp_ms).toISOString(),
          resolved_at: null,
        });
      } else if (env.type === "RESOLUTION") {
        const p = env.payload as { intention_id: string };
        const t = intentionMap.get(p.intention_id);
        if (t) {
          intentionMap.set(p.intention_id, {
            ...t!,
            status: "resolved",
            resolved_at: new Date(env.timestamp_ms).toISOString(),
          });
        }
      } else if (env.type === "PIVOT") {
        const p = env.payload as { from_intention_id: string };
        const t = intentionMap.get(p.from_intention_id);
        if (t) {
          intentionMap.set(p.from_intention_id, { ...t!, status: "pivoted" });
        }
      } else if (env.type === "CONFLICT") {
        const p = env.payload as { intention_id: string };
        conflicts.set(p.intention_id, (conflicts.get(p.intention_id) || 0) + 1);
      } else if (env.type === "BELIEF") {
        const p = env.payload as Record<string, unknown>;
        const key = (p.key as string) || "";
        const arr = (beliefs.get(key) || []).filter(
          (b) => (b as { agent_id: string }).agent_id !== env.agent_id,
        );
        arr.push({
          agent_id: env.agent_id,
          key,
          value: p.value,
          confidence: Number(p.confidence ?? 0),
          source: (p.source as never) || "observed",
          updated_at: new Date(env.timestamp_ms).toISOString(),
        });
        beliefs.set(key, arr);
      } else if (env.type === "COST_REPORT") {
        const usd = Number(
          (env.payload as { estimated_usd?: number }).estimated_usd ?? 0,
        );
        costUsd += usd;
      }
    }
    return {
      intentions: Array.from(intentionMap.values()).filter(
        (x): x is NonNullable<typeof x> => x !== undefined,
      ),
      beliefs: beliefs as typeof session.beliefs,
      conflictsByIntention: conflicts,
      costUsd,
    };
  }, [
    cursor,
    visibleEvents,
    session.intentions,
    session.beliefs,
    session.conflictsByIntention,
    session.costUsd,
  ]);

  const agents = Array.from(session.agents.values());
  const intentions = replayState.intentions as NonNullable<
    typeof replayState.intentions
  >;
  const activeIntentions = intentions.filter((i) => i.status === "active").length;
  const conflictCount = Array.from(
    replayState.conflictsByIntention.values(),
  ).reduce((a, b) => a + b, 0);

  return (
    <main className="flex min-h-screen flex-col">
      {/* Top bar */}
      <header className="flex flex-wrap items-center gap-3 border-b border-line bg-bg-panel px-5 py-3">
        <Link
          href="/"
          className="text-text-secondary hover:text-text-primary text-sm"
        >
          ← sessions
        </Link>
        <span className="text-line">|</span>
        <h1 className="font-mono text-sm font-semibold">{sessionId}</h1>
        <ConnectionDot connected={session.connected} />
        {!isLive && (
          <span className="rounded bg-accent-amber/15 px-2 py-0.5 text-[10px] text-accent-amber">
            replay
          </span>
        )}
        <div className="ml-auto flex items-center gap-4 text-xs text-text-secondary">
          <Stat label="agents" value={agents.length} />
          <Stat label="active" value={activeIntentions} />
          <Stat
            label="conflicts"
            value={conflictCount}
            tone={conflictCount > 0 ? "red" : undefined}
          />
          <Stat label="cost" value={`$${replayState.costUsd.toFixed(4)}`} />
        </div>
      </header>

      {/* Body: 3-column grid */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[1fr_1fr_1fr] gap-4 p-4">
        <div className="space-y-4 min-h-0">
          <AgentGrid agents={agents} />
          <CostChart events={visibleEvents} totalUsd={replayState.costUsd} />
          <ReplayScrubber
            events={session.events}
            onCursorChange={setCursor}
            isLive={isLive}
          />
          <BeliefPanel beliefs={replayState.beliefs} />
        </div>
        <div className="min-h-0">
          <IntentionsTable
            intentions={intentions}
            conflictCount={replayState.conflictsByIntention}
          />
        </div>
        <div className="min-h-[60vh] lg:min-h-0">
          <EventStream events={visibleEvents} />
        </div>
      </div>
    </main>
  );
}

function ConnectionDot({ connected }: { connected: boolean }) {
  return (
    <div className="flex items-center gap-1.5 text-xs text-text-secondary">
      <span
        className={`block h-2 w-2 rounded-full ${
          connected ? "bg-accent-green" : "bg-muted"
        }`}
      />
      {connected ? "live" : "disconnected"}
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: "red" | "amber" | "green";
}) {
  const toneClass =
    tone === "red"
      ? "text-accent-red"
      : tone === "amber"
        ? "text-accent-amber"
        : tone === "green"
          ? "text-accent-green"
          : "text-text-primary";
  return (
    <span>
      <span className="text-muted">{label} </span>
      <span className={`font-mono ${toneClass}`}>{value}</span>
    </span>
  );
}
