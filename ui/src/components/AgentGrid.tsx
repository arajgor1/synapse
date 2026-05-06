"use client";

import type { Agent } from "@/lib/types";

const tierColor: Record<string, string> = {
  native: "text-accent-green",
  local_api: "text-accent-blue",
  hosted: "text-accent-amber",
};

export function AgentGrid({ agents }: { agents: Agent[] }) {
  if (agents.length === 0) {
    return (
      <div className="rounded-lg border border-line bg-bg-panel p-4 text-sm text-muted">
        Waiting for agents…
      </div>
    );
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {agents.map((a) => (
        <AgentCard key={a.id} agent={a} />
      ))}
    </div>
  );
}

function AgentCard({ agent }: { agent: Agent }) {
  const tier = agent.capabilities.tier;
  const tierClass = tierColor[tier] || "text-text-secondary";
  const isReasoning = agent.capabilities.is_reasoning_model;

  return (
    <div className="rounded-lg border border-line bg-bg-panel p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-mono font-semibold text-text-primary">
            {agent.id}
          </div>
          <div className="mt-0.5 text-xs text-text-secondary">
            <span className={tierClass}>{tier}</span>
            <span className="mx-1.5 text-line">·</span>
            <span>{agent.capabilities.backend_id}</span>
            {agent.capabilities.model_id && (
              <>
                <span className="mx-1.5 text-line">·</span>
                <span className="font-mono">
                  {agent.capabilities.model_id}
                </span>
              </>
            )}
          </div>
        </div>
        <StatusDot status={agent.status} />
      </div>

      {(agent.scopes_owned.length > 0 || agent.subscribes.length > 0) && (
        <div className="mt-3 space-y-1.5 text-xs">
          {agent.scopes_owned.length > 0 && (
            <div>
              <span className="text-muted">owns </span>
              <span className="font-mono text-text-secondary">
                {agent.scopes_owned.join(", ")}
              </span>
            </div>
          )}
          {agent.subscribes.length > 0 && (
            <div>
              <span className="text-muted">subs </span>
              <span className="font-mono text-text-secondary">
                {agent.subscribes.join(", ")}
              </span>
            </div>
          )}
        </div>
      )}

      {isReasoning && (
        <div className="mt-3 inline-block rounded bg-accent-amber/10 px-2 py-0.5 text-xs text-accent-amber">
          reasoning model
        </div>
      )}
    </div>
  );
}

function StatusDot({ status }: { status: Agent["status"] }) {
  const cls =
    status === "active"
      ? "bg-accent-green animate-pulse-fast"
      : status === "idle"
        ? "bg-muted"
        : "bg-accent-red";
  return (
    <div className="flex items-center gap-1.5 text-xs text-text-secondary">
      <span className={`block h-2 w-2 rounded-full ${cls}`} />
      {status}
    </div>
  );
}
