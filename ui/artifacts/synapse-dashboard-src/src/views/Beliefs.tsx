import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Brain } from "lucide-react";
import { beliefDivergence, events } from "@/synapse/data";

interface BeliefRow {
  agent: string;
  key: string;
  value: string;
  confidence: number;
  source: string;
  evidence: string;
}

export default function BeliefsView() {
  // Pull all BELIEF envelopes
  const beliefEvents = events.filter((e) => e.kind === "BELIEF");

  const rows: BeliefRow[] = beliefEvents.map((e) => {
    const valueMatch = e.summary.match(/asserts:\s*(.+)/);
    const value = valueMatch ? valueMatch[1] : e.summary;
    const key = e.scope.replace("world.metrics.", "");
    const confidence = typeof e.meta?.confidence === "number" ? e.meta.confidence : 0.5;
    return {
      agent: e.agent,
      key,
      value,
      confidence,
      source: "tool_result",
      evidence: e.id,
    };
  });

  return (
    <section className="px-6 py-4">
      <div className="mb-3 flex items-baseline justify-between">
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-foreground/70" />
          <h2 className="font-serif text-base font-semibold text-foreground">
            Beliefs
          </h2>
        </div>
        <span className="font-mono text-[11px] text-muted-foreground">
          {rows.length} beliefs · 1 divergence detected
        </span>
      </div>

      <Card className="rounded-md border border-border bg-card shadow-none">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-[11px] uppercase tracking-wider">Agent</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Key</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Value</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Confidence</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Source</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Evidence</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r, i) => (
              <TableRow key={i}>
                <TableCell className="text-[12px] text-foreground">{r.agent}</TableCell>
                <TableCell className="font-mono text-[11px] text-muted-foreground">{r.key}</TableCell>
                <TableCell className="font-mono text-[12px] text-foreground">{r.value}</TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-20 overflow-hidden rounded-full bg-secondary">
                      <div
                        className="h-full bg-envelope-belief"
                        style={{ width: `${r.confidence * 100}%` }}
                      />
                    </div>
                    <span className="tnum font-mono text-[11px] text-muted-foreground">
                      {r.confidence.toFixed(2)}
                    </span>
                  </div>
                </TableCell>
                <TableCell className="font-mono text-[11px] text-muted-foreground">{r.source}</TableCell>
                <TableCell className="font-mono text-[11px] text-foreground">{r.evidence}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      <div className="mt-6">
        <div className="mb-2 flex items-center gap-2">
          <h3 className="font-serif text-sm font-semibold text-foreground">
            Divergences
          </h3>
          <span className="rounded-full border border-envelope-belief/30 bg-envelope-belief/8 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-envelope-belief">
            {beliefDivergence.key}
          </span>
        </div>
        <Card className="rounded-md border border-border bg-card p-4 shadow-none">
          <div className="grid gap-3 md:grid-cols-2">
            {beliefDivergence.values.map((v, i) => (
              <div
                key={v.agent}
                className="flex flex-col gap-2 rounded-sm border border-border bg-background/60 p-3"
              >
                <div className="flex items-center justify-between">
                  <span className="text-[12px] font-medium text-foreground">{v.agent}</span>
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
          <div className="mt-3 border-t border-border pt-2 font-mono text-[11px] text-muted-foreground">
            BELIEF DIVERGENCE on <span className="text-foreground">revenue_formula</span>:
            {" "}2 distinct values across <span className="text-foreground">cleaner</span>, <span className="text-foreground">analyst</span>
            {" "}· detected at {beliefDivergence.detectedAt}
          </div>
        </Card>
      </div>
    </section>
  );
}
