"use client";

interface Props {
  file: string | null;
  content: string;
}

export function ArtifactPreview({ file, content }: Props) {
  if (!file) {
    return (
      <section className="rounded-lg border border-line bg-bg-panel p-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
          artifact preview
        </h3>
        <p className="mt-2 text-sm text-muted">
          Select an agent card to preview the file it produced.
        </p>
      </section>
    );
  }

  const lang = inferLang(file);
  const isEmpty = !content.trim();

  return (
    <section className="flex h-full flex-col rounded-lg border border-line bg-bg-panel p-4">
      <header className="mb-2 flex items-baseline justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
          artifact: <code className="font-mono normal-case text-accent-blue">{file}</code>
        </h3>
        <span className="text-[10px] text-muted">
          {content.length}B · {lang}
        </span>
      </header>

      {isEmpty ? (
        <div className="rounded border border-line bg-bg-panel2 p-4 text-sm text-muted">
          (empty — this artifact was not written)
        </div>
      ) : (
        <pre className="flex-1 overflow-auto rounded border border-line bg-bg-panel2 p-3 font-mono text-[12px] leading-relaxed text-text-primary">
          <code>{content}</code>
        </pre>
      )}
    </section>
  );
}

function inferLang(file: string): string {
  const dot = file.lastIndexOf(".");
  if (dot < 0) return "text";
  const ext = file.slice(dot + 1).toLowerCase();
  const map: Record<string, string> = {
    py: "python",
    md: "markdown",
    sh: "bash",
    json: "json",
    jsonl: "jsonl",
    ts: "typescript",
    tsx: "tsx",
    yaml: "yaml",
    yml: "yaml",
  };
  return map[ext] ?? ext;
}
