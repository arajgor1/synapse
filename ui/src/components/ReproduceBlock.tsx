"use client";

import { useState } from "react";

interface Props {
  commit: string;
}

export function ReproduceBlock({ commit }: Props) {
  const [copied, setCopied] = useState<string | null>(null);

  const cmds = [
    `git checkout ${commit}`,
    `cd bench/results/v32_app_bundle`,
    `pip install flask`,
    `python -c "import main; client = main.app.test_client(); print(client.get('/todos').status_code)"`,
  ];
  const block = cmds.join("\n");

  const copy = (label: string, text: string) => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      void navigator.clipboard.writeText(text).then(() => {
        setCopied(label);
        setTimeout(() => setCopied(null), 1400);
      });
    }
  };

  return (
    <section className="rounded-lg border border-line bg-bg-panel p-4">
      <header className="mb-2 flex items-baseline justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
          reproduce locally
        </h3>
        <button
          type="button"
          onClick={() => copy("all", block)}
          className="rounded border border-line bg-bg-panel2 px-2 py-0.5 text-[10px] uppercase tracking-wide text-text-secondary hover:border-accent-blue hover:text-accent-blue"
        >
          {copied === "all" ? "copied!" : "copy"}
        </button>
      </header>

      <pre className="overflow-auto rounded border border-line bg-bg-panel2 p-3 font-mono text-[12px] leading-relaxed text-text-primary">
        <code>{block}</code>
      </pre>

      <p className="mt-2 text-[11px] text-muted">
        Expected output: <code className="font-mono text-accent-green">200</code> — the Flask app the 10 cross-vendor agents collaboratively built actually serves HTTP traffic.
      </p>
    </section>
  );
}
