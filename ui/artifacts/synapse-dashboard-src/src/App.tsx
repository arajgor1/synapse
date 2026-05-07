import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Brain,
  CircleDot,
  Cpu,
  GitMerge,
  Layers,
  ScanLine,
  Sparkles,
  Workflow,
  X,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  agents,
  activeConflicts,
  beliefDivergence,
  events,
  kpis,
  sessionMeta,
  type Agent,
  type ConflictDetail,
  type Envelope,
  type EnvelopeKind,
  type Framework,
} from "@/synapse/data";
import AgentsView from "@/views/Agents";
import EventsView from "@/views/Events";
import MergesView from "@/views/Merges";
import BeliefsView from "@/views/Beliefs";
import PolicyView from "@/views/Policy";

type TabName = "Live" | "Agents" | "Events" | "Merges" | "Beliefs" | "Policy";

// --- small helpers -----------------------------------------------------------

const envelopeStyles: Record<
  EnvelopeKind,
  { dot: string; chip: string; label: string }
> = {
  INTENTION: {
    dot: "bg-envelope-intention",
    chip: "border-envelope-intention/30 text-envelope-intention bg-envelope-intention/8",
    label: "INTENTION",
  },
  RESOLUTION: {
    dot: "bg-envelope-resolution",
    chip: "border-envelope-resolution/30 text-envelope-resolution bg-envelope-resolution/8",
    label: "RESOLUTION",
  },
  CONFLICT: {
    dot: "bg-envelope-conflict",
    chip: "border-envelope-conflict/30 text-envelope-conflict bg-envelope-conflict/10",
    label: "CONFLICT",
  },
  BELIEF: {
    dot: "bg-envelope-belief",
    chip: "border-envelope-belief/30 text-envelope-belief bg-envelope-belief/8",
    label: "BELIEF",
  },
};

const frameworkStyles: Record<Framework, string> = {
  Hermes:    "bg-tangerine-100 text-tangerine-800 border-tangerine-300",
  LangGraph: "bg-emerald-100 text-emerald-800 border-emerald-300",
  CrewAI:    "bg-sky-100 text-sky-800 border-sky-300",
};

const statusStyles: Record<Agent["status"], { ring: string; dot: string; label: string }> = {
  active:        { ring: "ring-emerald-400/40", dot: "bg-emerald-500", label: "active" },
  deliberating:  { ring: "ring-amber-400/50",   dot: "bg-amber-500",   label: "deliberating" },
  blocked:       { ring: "ring-rose-400/50",    dot: "bg-rose-500",    label: "blocked" },
  merged:        { ring: "ring-stone-400/40",   dot: "bg-stone-400",   label: "merged" },
};

// --- top bar -----------------------------------------------------------------

function TopBar() {
  return (
    <header className="border-b border-border bg-card/60 backdrop-blur supports-[backdrop-filter]:bg-card/50">
      <div className="flex h-14 items-center gap-4 px-6">
        <div className="flex items-center gap-2.5">
          <div className="grid h-7 w-7 place-items-center rounded-sm bg-foreground text-background">
            <Workflow className="h-4 w-4" />
          </div>
          <span className="font-serif text-[22px] font-semibold tracking-tight text-foreground">
            Synapse
          </span>
          <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
            v0.1.0
          </span>
        </div>

        <Separator orientation="vertical" className="mx-2 h-6" />

        <div className="flex items-center gap-2">
          <span className="text-xs uppercase tracking-wider text-muted-foreground">
            session
          </span>
          <span className="rounded-full border border-border bg-secondary px-2.5 py-0.5 font-mono text-xs text-secondary-foreground">
            {sessionMeta.id}
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-60" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-accent" />
          </span>
          <span className="text-xs font-medium text-foreground">Live</span>
          <span className="font-mono text-[11px] text-muted-foreground">
            uptime {sessionMeta.uptime}
          </span>
        </div>

        <div className="ml-auto flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
          <span className="rounded-sm border border-dashed border-border px-2 py-0.5">
            {sessionMeta.policy}
          </span>
        </div>
      </div>
    </header>
  );
}

// --- left rail (sidebar nav) -------------------------------------------------

function LeftRail({
  activeTab,
  setActiveTab,
}: {
  activeTab: TabName;
  setActiveTab: (t: TabName) => void;
}) {
  const items: { icon: typeof Activity; label: TabName }[] = [
    { icon: Activity, label: "Live"    },
    { icon: Layers,   label: "Agents"  },
    { icon: ScanLine, label: "Events"  },
    { icon: GitMerge, label: "Merges"  },
    { icon: Brain,    label: "Beliefs" },
    { icon: Cpu,      label: "Policy"  },
  ];
  return (
    <aside className="hidden w-14 shrink-0 border-r border-border bg-card/40 lg:flex lg:flex-col">
      <div className="flex flex-col items-center gap-1 py-3">
        {items.map((it) => {
          const active = activeTab === it.label;
          return (
            <Tooltip key={it.label}>
              <TooltipTrigger asChild>
                <button
                  onClick={() => setActiveTab(it.label)}
                  aria-current={active ? "page" : undefined}
                  className={
                    "grid h-9 w-9 place-items-center rounded-md transition-colors " +
                    (active
                      ? "bg-foreground text-background"
                      : "text-muted-foreground hover:bg-secondary hover:text-foreground")
                  }
                >
                  <it.icon className="h-4 w-4" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="right">{it.label}</TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </aside>
  );
}

// --- KPI strip ---------------------------------------------------------------

function KpiStrip() {
  const cards = [
    { label: "Agents active",   value: kpis.agentsActive,   sub: "of 8 connected",      icon: Layers,        accent: false },
    { label: "Intentions",      value: kpis.intentions,     sub: "this session",        icon: Activity,      accent: false },
    { label: "Conflicts caught",value: kpis.conflictsCaught,sub: "1 manual-review",     icon: AlertTriangle, accent: true  },
    { label: "Auto-merges",     value: kpis.autoMerges,     sub: "avg 1.4s resolution", icon: GitMerge,      accent: false },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 px-6 py-4 md:grid-cols-4">
      {cards.map((c) => (
        <Card
          key={c.label}
          className="rounded-md border border-border bg-card shadow-none"
        >
          <CardContent className="flex items-start justify-between gap-3 p-4">
            <div>
              <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                {c.label}
              </div>
              <div className="tnum mt-1 font-serif text-3xl leading-none text-foreground">
                {c.value}
              </div>
              <div className="mt-1.5 font-mono text-[11px] text-muted-foreground">
                {c.sub}
              </div>
            </div>
            <div
              className={
                "grid h-8 w-8 place-items-center rounded-sm " +
                (c.accent
                  ? "bg-accent/10 text-accent"
                  : "bg-secondary text-foreground/70")
              }
            >
              <c.icon className="h-4 w-4" />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// --- agent grid --------------------------------------------------------------

function AgentTile({ agent }: { agent: Agent }) {
  const s = statusStyles[agent.status];
  const dotText = s.dot.replace("bg-", "text-");
  return (
    <Card className="group relative flex flex-col gap-3 overflow-hidden rounded-md border border-border bg-card p-4 shadow-none transition-shadow hover:shadow-sm">
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-accent/40 to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <div
            className={
              "relative grid h-8 w-8 shrink-0 place-items-center rounded-full bg-secondary ring-2 " +
              s.ring
            }
          >
            <span className="font-serif text-[13px] font-semibold text-foreground">
              {agent.name.slice(0, 2)}
            </span>
            <span
              className={
                "absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full ring-2 ring-card animate-pulse-soft " +
                s.dot
              }
            />
          </div>
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-foreground">
              {agent.name}
            </div>
            <div className="truncate text-[11px] text-muted-foreground">
              {agent.role}
            </div>
          </div>
        </div>
        <Badge
          variant="outline"
          className={
            "rounded-full border px-2 py-0 text-[10px] font-medium tracking-wide " +
            frameworkStyles[agent.framework]
          }
        >
          {agent.framework}
        </Badge>
      </div>

      <div className="rounded-sm border border-dashed border-border bg-background/60 px-2.5 py-1.5">
        <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          intention
        </div>
        <div className="mt-0.5 line-clamp-2 font-mono text-[12px] leading-snug text-foreground">
          {agent.intention}
        </div>
      </div>

      <div className="flex items-center justify-between text-[11px]">
        <span className="flex items-center gap-1.5 text-muted-foreground">
          <CircleDot className={"h-2.5 w-2.5 " + dotText} />
          {s.label}
        </span>
        <span className="font-mono text-muted-foreground">
          {agent.ticks} env<span className="text-muted-foreground/60">·tick</span>
        </span>
      </div>
    </Card>
  );
}

function AgentGrid() {
  return (
    <section className="px-6">
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="font-serif text-base font-semibold text-foreground">
          Agents
        </h2>
        <span className="font-mono text-[11px] text-muted-foreground">
          {agents.length} connected · 3 frameworks
        </span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {agents.slice(0, 8).map((a) => (
          <AgentTile key={a.id} agent={a} />
        ))}
      </div>
    </section>
  );
}

// --- live event stream -------------------------------------------------------

function EventRow({
  e,
  onSelectConflict,
}: {
  e: Envelope;
  onSelectConflict: (id: string) => void;
}) {
  const s = envelopeStyles[e.kind];
  const isConflict = e.kind === "CONFLICT";
  return (
    <div
      className={
        "relative grid grid-cols-[auto,1fr,auto] items-start gap-3 px-4 py-2.5 animate-fade-in " +
        (isConflict ? "cursor-pointer hover:bg-envelope-conflict/5" : "")
      }
      onClick={isConflict ? () => onSelectConflict(e.id) : undefined}
    >
      <div className="flex flex-col items-center pt-1">
        <span className={"h-2 w-2 rounded-full " + s.dot} />
        <span className="mt-1 h-full w-px bg-border" />
      </div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={
              "rounded-sm border px-1.5 py-0 font-mono text-[10px] font-semibold tracking-wider " +
              s.chip
            }
          >
            {s.label}
          </span>
          <span className="font-mono text-[11px] text-muted-foreground">
            {e.id}
          </span>
          <span className="text-[12px] text-foreground">
            <span className="font-medium">{e.agent}</span>
            <span className="text-muted-foreground"> on </span>
            <span className="font-mono">{e.scope}</span>
          </span>
        </div>
        <div className="mt-1 truncate font-mono text-[12px] text-foreground/80">
          {e.summary}
        </div>
        {e.meta && (
          <div className="mt-1 flex flex-wrap gap-1.5">
            {Object.entries(e.meta).map(([k, v]) => (
              <span
                key={k}
                className="rounded-sm border border-border bg-secondary/60 px-1.5 py-0 font-mono text-[10px] text-muted-foreground"
              >
                {k}={String(v)}
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="pt-1 text-right">
        <div className="font-mono text-[11px] text-muted-foreground">
          {e.age}
        </div>
        <div className="font-mono text-[10px] text-muted-foreground/70">
          {e.ts}
        </div>
      </div>
    </div>
  );
}

function EventStream({
  onSelectConflict,
}: {
  onSelectConflict: (id: string) => void;
}) {
  const [filter, setFilter] = useState<EnvelopeKind | "ALL">("ALL");
  const filtered = useMemo(
    () => (filter === "ALL" ? events : events.filter((e) => e.kind === filter)),
    [filter]
  );
  const kinds: (EnvelopeKind | "ALL")[] = ["ALL", "INTENTION", "RESOLUTION", "CONFLICT", "BELIEF"];

  return (
    <Card className="flex h-full min-h-[420px] flex-col rounded-md border border-border bg-card shadow-none">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Sparkles className="h-3.5 w-3.5 text-accent" />
          <h3 className="font-serif text-sm font-semibold text-foreground">
            Live event stream
          </h3>
          <span className="font-mono text-[11px] text-muted-foreground">
            {filtered.length} envelopes
          </span>
        </div>
        <div className="flex items-center gap-1">
          {kinds.map((k) => (
            <button
              key={k}
              onClick={() => setFilter(k)}
              className={
                "rounded-full border px-2 py-0.5 font-mono text-[10px] tracking-wide transition-colors " +
                (filter === k
                  ? "border-foreground bg-foreground text-background"
                  : "border-border text-muted-foreground hover:bg-secondary hover:text-foreground")
              }
            >
              {k}
            </button>
          ))}
        </div>
      </div>
      <div className="synapse-scroll flex-1 overflow-y-auto py-1 pr-1">
        {filtered.map((e) => (
          <EventRow key={e.id} e={e} onSelectConflict={onSelectConflict} />
        ))}
      </div>
      <div className="border-t border-border px-4 py-1.5 font-mono text-[10px] text-muted-foreground">
        click any <span className="text-envelope-conflict">CONFLICT</span> row to inspect →
      </div>
    </Card>
  );
}

// --- conflict drawer ---------------------------------------------------------

function ConflictDrawer({
  conflict,
  onClose,
}: {
  conflict: ConflictDetail | null;
  onClose: () => void;
}) {
  if (!conflict) return null;
  const sevTone = {
    high: "bg-envelope-conflict text-white",
    med:  "bg-amber-500 text-white",
    low:  "bg-stone-400 text-white",
  }[conflict.severity];

  return (
    <div className="pointer-events-none absolute inset-0 z-30 flex justify-end">
      <div
        className="pointer-events-auto absolute inset-0 bg-foreground/10 backdrop-blur-[1px]"
        onClick={onClose}
      />
      <aside className="pointer-events-auto relative flex h-full w-full max-w-md animate-slide-in-right flex-col border-l border-border bg-card shadow-xl">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-envelope-conflict" />
            <h3 className="font-serif text-base font-semibold text-foreground">
              Conflict detail
            </h3>
            <span className="font-mono text-[11px] text-muted-foreground">
              {conflict.id}
            </span>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 rounded-sm"
            onClick={onClose}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="flex flex-col gap-4 overflow-y-auto p-5">
          <div className="flex items-center gap-2">
            <span
              className={
                "rounded-full px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider " +
                sevTone
              }
            >
              {conflict.severity} severity
            </span>
            <span className="rounded-sm border border-border bg-secondary px-2 py-0.5 font-mono text-[11px]">
              {conflict.policy}
            </span>
          </div>

          <div>
            <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              overlapping scope
            </div>
            <div className="mt-1 rounded-sm border border-dashed border-border bg-background px-2.5 py-1.5 font-mono text-[12px] text-foreground">
              {conflict.scope}
            </div>
          </div>

          <div className="grid gap-3">
            <div>
              <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                {conflict.agentA.name}
              </div>
              <div className="mt-1 rounded-sm border-l-2 border-envelope-intention bg-envelope-intention/5 p-2 font-mono text-[12px] text-foreground/90">
                {conflict.agentA.intention}
              </div>
            </div>
            <div>
              <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                {conflict.agentB.name}
              </div>
              <div className="mt-1 rounded-sm border-l-2 border-envelope-intention bg-envelope-intention/5 p-2 font-mono text-[12px] text-foreground/90">
                {conflict.agentB.intention}
              </div>
            </div>
          </div>

          <Separator />

          <div>
            <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              policy decision
            </div>
            <div className="mt-1.5 grid grid-cols-3 gap-2">
              <div className="rounded-sm bg-secondary p-2">
                <div className="text-[10px] uppercase text-muted-foreground">strategy</div>
                <div className="mt-0.5 font-mono text-[12px] font-medium text-foreground">
                  {conflict.status === "auto-merged" ? "auto_merge" : "defer"}
                </div>
              </div>
              <div className="rounded-sm bg-secondary p-2">
                <div className="text-[10px] uppercase text-muted-foreground">priors</div>
                <div className="mt-0.5 font-mono text-[12px] font-medium text-foreground">
                  {conflict.priors}
                </div>
              </div>
              <div className="rounded-sm bg-secondary p-2">
                <div className="text-[10px] uppercase text-muted-foreground">resolved</div>
                <div className="mt-0.5 font-mono text-[12px] font-medium text-foreground">
                  {conflict.resolutionMs > 0 ? `${(conflict.resolutionMs / 1000).toFixed(2)}s` : "—"}
                </div>
              </div>
            </div>
            <div
              className={
                "mt-2 flex items-center gap-2 rounded-sm border px-2.5 py-1.5 font-mono text-[11px] " +
                (conflict.status === "auto-merged"
                  ? "border-envelope-resolution/30 bg-envelope-resolution/5 text-envelope-resolution"
                  : "border-amber-400/40 bg-amber-50 text-amber-800")
              }
            >
              {conflict.status === "auto-merged" ? (
                <>
                  <GitMerge className="h-3.5 w-3.5" />
                  auto_merge: {conflict.priors} priors composed → merged in {(conflict.resolutionMs / 1000).toFixed(1)}s
                </>
              ) : (
                <>
                  <AlertTriangle className="h-3.5 w-3.5" />
                  awaiting manual review — escalated to operator
                </>
              )}
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
}

// --- belief divergence panel -------------------------------------------------

function BeliefPanel() {
  const b = beliefDivergence;
  return (
    <Card className="rounded-md border border-border bg-card shadow-none">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Brain className="h-3.5 w-3.5 text-envelope-belief" />
          <h3 className="font-serif text-sm font-semibold text-foreground">
            Belief divergence
          </h3>
          <span className="font-mono text-[11px] text-muted-foreground">
            on {b.key}
          </span>
        </div>
        <span className="rounded-full border border-envelope-belief/30 bg-envelope-belief/8 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-envelope-belief">
          divergence
        </span>
      </div>
      <div className="grid gap-3 p-4 md:grid-cols-2">
        {b.values.map((v, i) => (
          <div
            key={v.agent}
            className="relative flex flex-col gap-2 rounded-sm border border-border bg-background/60 p-3"
          >
            <div className="flex items-center justify-between">
              <span className="text-[12px] font-medium text-foreground">
                {v.agent}
              </span>
              <span className="font-mono text-[10px] text-muted-foreground">
                conf {v.confidence.toFixed(2)}
              </span>
            </div>
            <div className="rounded-sm border border-dashed border-border bg-card px-2.5 py-2 font-mono text-[13px] leading-tight text-foreground">
              {v.value}
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-secondary">
              <div
                className={i === 0 ? "h-full bg-envelope-belief/70" : "h-full bg-envelope-belief"}
                style={{ width: `${v.confidence * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>
      <div className="border-t border-border px-4 py-2 font-mono text-[11px] text-muted-foreground">
        BELIEF DIVERGENCE on <span className="text-foreground">revenue_formula</span>:
        {" "}2 distinct values across <span className="text-foreground">cleaner</span>, <span className="text-foreground">analyst</span>
        {" "}· detected at {b.detectedAt}
      </div>
    </Card>
  );
}

// --- live view (the original dashboard) --------------------------------------

function LiveView({
  activeConflictId,
  setActiveConflictId,
}: {
  activeConflictId: string | null;
  setActiveConflictId: (id: string | null) => void;
}) {
  return (
    <>
      <KpiStrip />
      <AgentGrid />
      <div className="grid gap-3 px-6 py-4 lg:grid-cols-[1fr,minmax(0,0.9fr)]">
        <EventStream onSelectConflict={setActiveConflictId} />
        <div className="flex flex-col gap-3">
          <Card className="rounded-md border border-border bg-card shadow-none">
            <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
              <div className="flex items-center gap-2">
                <AlertTriangle className="h-3.5 w-3.5 text-envelope-conflict" />
                <h3 className="font-serif text-sm font-semibold text-foreground">
                  Active conflicts
                </h3>
              </div>
              <span className="font-mono text-[11px] text-muted-foreground">
                {activeConflicts.length} total · 1 manual
              </span>
            </div>
            <div className="divide-y divide-border">
              {activeConflicts.map((c) => (
                <button
                  key={c.id}
                  onClick={() => setActiveConflictId(c.id)}
                  className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-secondary/40"
                >
                  <span
                    className={
                      "mt-1 h-2 w-2 rounded-full " +
                      (c.severity === "high"
                        ? "bg-envelope-conflict"
                        : c.severity === "med"
                        ? "bg-amber-500"
                        : "bg-stone-400")
                    }
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[11px] text-muted-foreground">
                        {c.id}
                      </span>
                      <span className="rounded-sm border border-border bg-secondary px-1.5 py-0 font-mono text-[10px] text-foreground">
                        {c.policy}
                      </span>
                      <span
                        className={
                          "ml-auto rounded-full px-1.5 py-0 font-mono text-[10px] " +
                          (c.status === "auto-merged"
                            ? "bg-envelope-resolution/10 text-envelope-resolution"
                            : "bg-amber-100 text-amber-800")
                        }
                      >
                        {c.status}
                      </span>
                    </div>
                    <div className="mt-1 truncate font-mono text-[12px] text-foreground">
                      {c.scope}
                    </div>
                    <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
                      {c.agentA.name} ↔ {c.agentB.name} · {c.priors} priors
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </Card>
        </div>
      </div>
      <div className="px-6 pb-8">
        <BeliefPanel />
      </div>
      {/* activeConflictId is referenced to silence unused-prop warning */}
      <span className="hidden">{activeConflictId ?? ""}</span>
    </>
  );
}

// --- main app ----------------------------------------------------------------

export default function App() {
  const [activeTab, setActiveTab] = useState<TabName>("Live");
  const [activeConflictId, setActiveConflictId] = useState<string | null>(null);

  // open the most recent high-severity conflict on first paint, briefly (Live only)
  useEffect(() => {
    if (activeTab !== "Live") return;
    const t = setTimeout(() => setActiveConflictId(activeConflicts[0].id), 700);
    return () => clearTimeout(t);
  }, [activeTab]);

  const conflict = useMemo(
    () => activeConflicts.find((c) => c.id === activeConflictId) ?? null,
    [activeConflictId]
  );

  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex min-h-screen flex-col bg-background synapse-grain text-foreground">
        <TopBar />
        <div className="relative flex flex-1 overflow-hidden">
          <LeftRail activeTab={activeTab} setActiveTab={setActiveTab} />
          <main className="flex-1 overflow-y-auto">
            {activeTab === "Live" && (
              <LiveView
                activeConflictId={activeConflictId}
                setActiveConflictId={setActiveConflictId}
              />
            )}
            {activeTab === "Agents"  && <AgentsView  />}
            {activeTab === "Events"  && <EventsView  />}
            {activeTab === "Merges"  && <MergesView  />}
            {activeTab === "Beliefs" && <BeliefsView />}
            {activeTab === "Policy"  && <PolicyView  />}
          </main>

          {activeTab === "Live" && (
            <ConflictDrawer
              conflict={conflict}
              onClose={() => setActiveConflictId(null)}
            />
          )}
        </div>

        <footer className="border-t border-border bg-card/40 px-6 py-2 font-mono text-[11px] text-muted-foreground">
          synapse · cross-framework agent coordination protocol · v0.1.0-alpha
        </footer>
      </div>
    </TooltipProvider>
  );
}
