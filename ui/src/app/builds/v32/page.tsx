"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Bundle } from "@/lib/bundle";
import { VerdictBand } from "@/components/VerdictBand";
import { VendorAgentGrid } from "@/components/VendorAgentGrid";
import { ArtifactPreview } from "@/components/ArtifactPreview";
import { EnvelopeTimeline } from "@/components/EnvelopeTimeline";
import { ReproduceBlock } from "@/components/ReproduceBlock";

export default function BuildV32Page() {
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<string>("main.py");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/builds/v32");
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = (await r.json()) as Bundle;
        if (!cancelled) setBundle(d);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="mx-auto max-w-7xl px-5 py-6">
      <nav className="mb-5 flex items-center gap-3 text-sm">
        <Link href="/" className="text-text-secondary hover:text-text-primary">
          ← home
        </Link>
        <span className="text-line">/</span>
        <span className="font-mono text-text-primary">builds/v32</span>
      </nav>

      {error && (
        <div className="mb-4 rounded border border-accent-red/40 bg-accent-red/10 p-3 text-sm text-accent-red">
          Failed to load build bundle: {error}
          <p className="mt-1 text-xs text-text-secondary">
            The bundle lives at <code className="font-mono">bench/results/v32_app_bundle/</code>.
            If you're running the UI from outside the repo, check the path
            resolution in <code className="font-mono">src/app/api/builds/v32/route.ts</code>.
          </p>
        </div>
      )}

      {!bundle && !error && (
        <p className="text-sm text-muted">Loading bundle…</p>
      )}

      {bundle && (
        <>
          <div className="mb-5">
            <VerdictBand
              summary={bundle.summary}
              session={bundle.session}
              commit={bundle.commit}
            />
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
            <div className="space-y-4 min-w-0">
              <VendorAgentGrid
                roles={bundle.roles}
                selected={selectedFile}
                onSelect={setSelectedFile}
              />
              <ReproduceBlock commit={bundle.commit} />
            </div>

            <div className="grid grid-cols-1 gap-4 min-w-0">
              <div className="min-h-[360px]">
                <ArtifactPreview
                  file={selectedFile}
                  content={bundle.files[selectedFile] ?? ""}
                />
              </div>
              <div className="min-h-[280px]">
                <EnvelopeTimeline envelopes={bundle.envelopes} />
              </div>
            </div>
          </div>

          <footer className="mt-6 text-xs text-muted">
            Built on Modal {new Date(bundle.produced_at).toLocaleString()} · synapse-protocol v0.2.8 · commit{" "}
            <a
              href={`https://github.com/arajgor1/synapse/commit/${bundle.commit}`}
              className="font-mono text-accent-blue hover:underline"
            >
              {bundle.commit}
            </a>
          </footer>
        </>
      )}
    </main>
  );
}
