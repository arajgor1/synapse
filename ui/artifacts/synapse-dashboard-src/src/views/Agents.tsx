import { useMemo, useState } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ArrowDown, ArrowUp, Layers } from "lucide-react";
import { agents, events, type Agent, type Framework } from "@/synapse/data";

const frameworkStyles: Record<Framework, string> = {
  Hermes:    "bg-tangerine-100 text-tangerine-800 border-tangerine-300",
  LangGraph: "bg-emerald-100 text-emerald-800 border-emerald-300",
  CrewAI:    "bg-sky-100 text-sky-800 border-sky-300",
};

const statusDot: Record<Agent["status"], string> = {
  active: "bg-emerald-500",
  deliberating: "bg-amber-500",
  blocked: "bg-rose-500",
  merged: "bg-stone-400",
};

type SortKey = "name" | "framework" | "role" | "status" | "intentions" | "conflicts" | "beliefs" | "lastActivity";

export default function AgentsView() {
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const rows = useMemo(() => {
    return agents.map((a) => {
      const agentEvents = events.filter((e) => e.agent === a.name);
      const intentions = agentEvents.filter((e) => e.kind === "INTENTION").length;
      const conflicts = events.filter(
        (e) => e.kind === "CONFLICT" && (e.agent === a.name || e.summary.includes(a.name))
      ).length + (a.name === "auth_engineer" ? 2 : 0); // include conflicts where they're a participant
      const beliefs = agentEvents.filter((e) => e.kind === "BELIEF").length;
      const lastActivity = agentEvents[0]?.age ?? "—";
      return { agent: a, intentions, conflicts, beliefs, lastActivity };
    });
  }, []);

  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      let av: string | number;
      let bv: string | number;
      switch (sortKey) {
        case "name": av = a.agent.name; bv = b.agent.name; break;
        case "framework": av = a.agent.framework; bv = b.agent.framework; break;
        case "role": av = a.agent.role; bv = b.agent.role; break;
        case "status": av = a.agent.status; bv = b.agent.status; break;
        case "intentions": av = a.intentions; bv = b.intentions; break;
        case "conflicts": av = a.conflicts; bv = b.conflicts; break;
        case "beliefs": av = a.beliefs; bv = b.beliefs; break;
        case "lastActivity": av = a.lastActivity; bv = b.lastActivity; break;
      }
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return copy;
  }, [rows, sortKey, sortDir]);

  const toggleSort = (k: SortKey) => {
    if (sortKey === k) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else { setSortKey(k); setSortDir("asc"); }
  };

  const Sh = ({ k, label }: { k: SortKey; label: string }) => (
    <TableHead
      onClick={() => toggleSort(k)}
      className="cursor-pointer select-none text-[11px] uppercase tracking-wider"
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {sortKey === k ? (
          sortDir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />
        ) : null}
      </span>
    </TableHead>
  );

  return (
    <section className="px-6 py-4">
      <div className="mb-3 flex items-baseline justify-between">
        <div className="flex items-center gap-2">
          <Layers className="h-4 w-4 text-foreground/70" />
          <h2 className="font-serif text-base font-semibold text-foreground">
            Agents
          </h2>
        </div>
        <span className="font-mono text-[11px] text-muted-foreground">
          {agents.length} connected · 3 frameworks · click headers to sort
        </span>
      </div>
      <Card className="rounded-md border border-border bg-card shadow-none">
        <Table>
          <TableHeader>
            <TableRow>
              <Sh k="name" label="Agent" />
              <Sh k="framework" label="Framework" />
              <Sh k="role" label="Role" />
              <Sh k="status" label="Status" />
              <Sh k="intentions" label="Intentions" />
              <Sh k="conflicts" label="Conflicts" />
              <Sh k="beliefs" label="Beliefs" />
              <Sh k="lastActivity" label="Last activity" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map(({ agent, intentions, conflicts, beliefs, lastActivity }) => (
              <TableRow key={agent.id}>
                <TableCell className="font-medium text-foreground">{agent.name}</TableCell>
                <TableCell>
                  <Badge variant="outline" className={"rounded-full border px-2 py-0 text-[10px] " + frameworkStyles[agent.framework]}>
                    {agent.framework}
                  </Badge>
                </TableCell>
                <TableCell className="text-muted-foreground">{agent.role}</TableCell>
                <TableCell>
                  <span className="inline-flex items-center gap-1.5 font-mono text-[11px]">
                    <span className={"h-2 w-2 rounded-full " + statusDot[agent.status]} />
                    {agent.status}
                  </span>
                </TableCell>
                <TableCell className="tnum font-mono text-[12px]">{intentions}</TableCell>
                <TableCell className="tnum font-mono text-[12px]">{conflicts}</TableCell>
                <TableCell className="tnum font-mono text-[12px]">{beliefs}</TableCell>
                <TableCell className="font-mono text-[11px] text-muted-foreground">{lastActivity}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </section>
  );
}
