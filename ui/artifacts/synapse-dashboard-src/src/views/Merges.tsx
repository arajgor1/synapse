import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { GitMerge } from "lucide-react";
import { activeConflicts, events } from "@/synapse/data";

const sevTone: Record<"low" | "med" | "high", string> = {
  high: "bg-envelope-conflict text-white",
  med:  "bg-amber-500 text-white",
  low:  "bg-stone-400 text-white",
};

// Simple deterministic diff blocks per merge — synthesized from the conflict data.
function getDiff(id: string) {
  if (id === "ENV-2c40") {
    return {
      before: [
        "ALTER TABLE users",
        "  ADD COLUMN last_login_at TIMESTAMP NULL;",
      ],
      after: [
        "ALTER TABLE users",
        "  ADD COLUMN last_login_at TIMESTAMP NULL,",
        "  ADD COLUMN refresh_token_hash VARCHAR(128) NOT NULL;",
      ],
    };
  }
  return {
    before: ["// rotate refresh_token on /refresh"],
    after:  ["// rotate refresh_token on /refresh", "// + replay-nonce check (lg_security)"],
  };
}

export default function MergesView() {
  const merges = activeConflicts.filter((c) => c.status === "auto-merged");

  return (
    <section className="px-6 py-4">
      <div className="mb-3 flex items-baseline justify-between">
        <div className="flex items-center gap-2">
          <GitMerge className="h-4 w-4 text-foreground/70" />
          <h2 className="font-serif text-base font-semibold text-foreground">
            Auto-merges
          </h2>
        </div>
        <span className="font-mono text-[11px] text-muted-foreground">
          {merges.length} resolved this session
        </span>
      </div>

      <div className="grid gap-4">
        {merges.map((m) => {
          const diff = getDiff(m.id);
          const resolutionEvent = events.find(
            (e) => e.kind === "RESOLUTION" && e.scope === m.scope
          );
          const model = "claude-opus-4.7";
          return (
            <Card key={m.id} className="rounded-md border border-border bg-card p-4 shadow-none">
              <div className="flex flex-wrap items-center gap-3">
                <span className={"rounded-full px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider " + sevTone[m.severity]}>
                  {m.severity}
                </span>
                <span className="font-mono text-[11px] text-muted-foreground">{m.id}</span>
                <span className="rounded-sm border border-border bg-secondary px-1.5 py-0 font-mono text-[10px] text-foreground">
                  {m.policy}
                </span>
                <span className="ml-auto font-mono text-[11px] text-muted-foreground">
                  {m.scope}
                </span>
              </div>

              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <div className="rounded-sm border border-dashed border-border bg-background/60 p-2.5">
                  <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                    {m.agentA.name} (prior A)
                  </div>
                  <div className="mt-1 font-mono text-[12px] leading-snug text-foreground">
                    {m.agentA.intention}
                  </div>
                </div>
                <div className="rounded-sm border border-dashed border-border bg-background/60 p-2.5">
                  <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                    {m.agentB.name} (prior B)
                  </div>
                  <div className="mt-1 font-mono text-[12px] leading-snug text-foreground">
                    {m.agentB.intention}
                  </div>
                </div>
              </div>

              <Separator className="my-3" />

              <div className="grid grid-cols-3 gap-2">
                <div className="rounded-sm bg-secondary p-2">
                  <div className="text-[10px] uppercase text-muted-foreground">model</div>
                  <div className="mt-0.5 font-mono text-[12px] font-medium text-foreground">{model}</div>
                </div>
                <div className="rounded-sm bg-secondary p-2">
                  <div className="text-[10px] uppercase text-muted-foreground">priors composed</div>
                  <div className="mt-0.5 font-mono text-[12px] font-medium text-foreground">{m.priors}</div>
                </div>
                <div className="rounded-sm bg-secondary p-2">
                  <div className="text-[10px] uppercase text-muted-foreground">time-to-resolve</div>
                  <div className="mt-0.5 font-mono text-[12px] font-medium text-foreground">
                    {(m.resolutionMs / 1000).toFixed(2)}s
                  </div>
                </div>
              </div>

              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <div className="rounded-sm border border-border bg-background p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      before (one prior)
                    </span>
                    <span className="font-mono text-[10px] text-muted-foreground">−</span>
                  </div>
                  <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[11.5px] leading-relaxed text-foreground/90">
{diff.before.join("\n")}
                  </pre>
                </div>
                <div className="rounded-sm border border-envelope-resolution/30 bg-envelope-resolution/5 p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-[10px] font-medium uppercase tracking-wider text-envelope-resolution">
                      after (merged)
                    </span>
                    <span className="font-mono text-[10px] text-envelope-resolution">+</span>
                  </div>
                  <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[11.5px] leading-relaxed text-foreground/90">
{diff.after.join("\n")}
                  </pre>
                </div>
              </div>

              {resolutionEvent && (
                <div className="mt-3 rounded-sm border border-envelope-resolution/30 bg-envelope-resolution/5 px-2.5 py-1.5 font-mono text-[11px] text-envelope-resolution">
                  <GitMerge className="mr-1 inline h-3.5 w-3.5" />
                  {resolutionEvent.summary}
                </div>
              )}
            </Card>
          );
        })}
      </div>
    </section>
  );
}
