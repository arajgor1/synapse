"use client";

import Link from "next/link";
import { use } from "react";
import { useSession } from "@/lib/useSession";
import { AgentGrid } from "@/components/AgentGrid";
import { EventStream } from "@/components/EventStream";
import { IntentionsTable } from "@/components/IntentionsTable";
import { BeliefPanel } from "@/components/BeliefPanel";

export default function SessionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const sessionId = decodeURIComponent(id);
  const session = useSession(sessionId);

  const agents = Array.from(session.agents.values());
  const intentions = Array.from(session.intentions.values());
  const activeIntentions = intentions.filter((i) => i.status === "active").length;
  const conflictCount = Array.from(session.conflictsByIntention.values()).reduce(
    (a, b) => a + b,
    0,
  );

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
        <div className="ml-auto flex items-center gap-4 text-xs text-text-secondary">
          <Stat label="agents" value={agents.length} />
          <Stat label="active" value={activeIntentions} />
          <Stat
            label="conflicts"
            value={conflictCount}
            tone={conflictCount > 0 ? "red" : undefined}
          />
          <Stat
            label="cost"
            value={`$${session.costUsd.toFixed(4)}`}
          />
        </div>
      </header>

      {/* Body: 3-column grid */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[1fr_1fr_1fr] gap-4 p-4">
        <div className="space-y-4 min-h-0">
          <AgentGrid agents={agents} />
          <BeliefPanel beliefs={session.beliefs} />
        </div>
        <div className="min-h-0">
          <IntentionsTable
            intentions={intentions}
            conflictCount={session.conflictsByIntention}
          />
        </div>
        <div className="min-h-[60vh] lg:min-h-0">
          <EventStream events={session.events} />
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
