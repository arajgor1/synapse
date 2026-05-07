import { useMemo, useState } from "react";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ScanLine } from "lucide-react";
import { events, type EnvelopeKind } from "@/synapse/data";

const envelopeChip: Record<EnvelopeKind, string> = {
  INTENTION:  "border-envelope-intention/30 text-envelope-intention bg-envelope-intention/8",
  RESOLUTION: "border-envelope-resolution/30 text-envelope-resolution bg-envelope-resolution/8",
  CONFLICT:   "border-envelope-conflict/30 text-envelope-conflict bg-envelope-conflict/10",
  BELIEF:     "border-envelope-belief/30 text-envelope-belief bg-envelope-belief/8",
};

type Filter = "ALL" | EnvelopeKind;

export default function EventsView() {
  const [filter, setFilter] = useState<Filter>("ALL");

  const filtered = useMemo(
    () => (filter === "ALL" ? events : events.filter((e) => e.kind === filter)),
    [filter]
  );

  const pills: Filter[] = ["ALL", "INTENTION", "RESOLUTION", "CONFLICT", "BELIEF"];

  return (
    <section className="px-6 py-4">
      <div className="mb-3 flex items-baseline justify-between">
        <div className="flex items-center gap-2">
          <ScanLine className="h-4 w-4 text-foreground/70" />
          <h2 className="font-serif text-base font-semibold text-foreground">
            Events
          </h2>
        </div>
        <span className="font-mono text-[11px] text-muted-foreground">
          {filtered.length} of {events.length} envelopes
        </span>
      </div>

      <div className="mb-3 flex items-center gap-1.5">
        {pills.map((p) => (
          <button
            key={p}
            onClick={() => setFilter(p)}
            className={
              "rounded-full border px-2.5 py-0.5 font-mono text-[10px] tracking-wide transition-colors " +
              (filter === p
                ? "border-foreground bg-foreground text-background"
                : "border-border text-muted-foreground hover:bg-secondary hover:text-foreground")
            }
          >
            {p}
          </button>
        ))}
      </div>

      <Card className="rounded-md border border-border bg-card shadow-none">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-[11px] uppercase tracking-wider">Time</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Type</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Envelope</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Agent</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Scope</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Payload</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((e) => (
              <TableRow key={e.id}>
                <TableCell className="font-mono text-[11px] text-muted-foreground whitespace-nowrap">{e.ts}</TableCell>
                <TableCell>
                  <span className={"rounded-sm border px-1.5 py-0 font-mono text-[10px] font-semibold tracking-wider " + envelopeChip[e.kind]}>
                    {e.kind}
                  </span>
                </TableCell>
                <TableCell className="font-mono text-[11px] text-foreground">{e.id}</TableCell>
                <TableCell className="text-[12px] text-foreground">{e.agent}</TableCell>
                <TableCell className="font-mono text-[11px] text-muted-foreground">{e.scope}</TableCell>
                <TableCell className="font-mono text-[11px] text-foreground/80 max-w-md truncate">{e.summary}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </section>
  );
}
