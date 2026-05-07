import { Card } from "@/components/ui/card";
import { Cpu } from "lucide-react";

interface PolicyOption {
  key: string;
  value: string;
  description: string;
}

const policy: PolicyOption[] = [
  {
    key: "merge_policy",
    value: "auto_merge",
    description: "Compose priors into a single resolution when scopes overlap and intent is non-destructive.",
  },
  {
    key: "scope_lock",
    value: "soft",
    description: "Soft locks block writes only when an active conflict is unresolved; reads always pass.",
  },
  {
    key: "critical_scopes",
    value: '["billing.*", "auth.tokens.*"]',
    description: "Scopes that require manual review even when auto_merge would otherwise compose priors.",
  },
  {
    key: "emit_beliefs_from_tool_results",
    value: "true",
    description: "Tool results are converted to BELIEF envelopes with confidence inferred from the tool's schema.",
  },
  {
    key: "max_priors_per_merge",
    value: "8",
    description: "Hard cap on the number of priors that can be composed into a single auto-merge.",
  },
  {
    key: "deferred_review_ttl",
    value: "30m",
    description: "If a manual-review conflict isn't resolved within this window, it is escalated to the operator.",
  },
];

export default function PolicyView() {
  return (
    <section className="px-6 py-4">
      <div className="mb-3 flex items-baseline justify-between">
        <div className="flex items-center gap-2">
          <Cpu className="h-4 w-4 text-foreground/70" />
          <h2 className="font-serif text-base font-semibold text-foreground">
            Policy
          </h2>
        </div>
        <span className="font-mono text-[11px] text-muted-foreground">
          read-only · session ecom_v1
        </span>
      </div>

      <Card className="rounded-md border border-border bg-card shadow-none">
        <div className="divide-y divide-border">
          {policy.map((p) => (
            <div key={p.key} className="grid gap-2 px-4 py-3 sm:grid-cols-[260px,1fr,auto] sm:items-start">
              <div>
                <div className="font-mono text-[12px] font-medium text-foreground">{p.key}</div>
                <div className="mt-0.5 text-[11px] text-muted-foreground">{p.description}</div>
              </div>
              <div className="rounded-sm border border-dashed border-border bg-background/60 px-2.5 py-1.5 font-mono text-[12px] text-foreground sm:max-w-md">
                {p.value}
              </div>
              <div className="flex items-center sm:justify-end">
                <span className="rounded-full border border-border bg-secondary px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                  active
                </span>
              </div>
            </div>
          ))}
        </div>
      </Card>

      <div className="mt-3 rounded-sm border border-dashed border-border bg-card/60 px-3 py-2 font-mono text-[11px] text-muted-foreground">
        edit via <span className="text-foreground">config/policy.yaml</span> · changes apply at next session bootstrap
      </div>
    </section>
  );
}
