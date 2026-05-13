import { NextResponse } from "next/server";
import fs from "node:fs/promises";
import path from "node:path";
import {
  Bundle,
  buildRoles,
  parseEnvelopesJsonl,
} from "@/lib/bundle";

// The v32 bundle lives at bench/results/v32_app_bundle/ in the repo.
// We resolve relative to the UI process CWD, walking up to the repo root.
async function findBundleDir(): Promise<string> {
  const candidates = [
    "../bench/results/v32_app_bundle",
    "../../bench/results/v32_app_bundle",
    "../../../bench/results/v32_app_bundle",
    "bench/results/v32_app_bundle",
  ];
  for (const c of candidates) {
    const abs = path.resolve(process.cwd(), c);
    try {
      const st = await fs.stat(abs);
      if (st.isDirectory()) return abs;
    } catch {
      // continue
    }
  }
  throw new Error(
    `Could not locate bench/results/v32_app_bundle/ (looked in: ${candidates.join(", ")})`,
  );
}

export async function GET() {
  try {
    const dir = await findBundleDir();
    const fileNames = [
      "api_spec.md",
      "main.py",
      "test_app.py",
      "PLAN.md",
      "models.py",
      "README.md",
      "LINT.md",
      "schemas.py",
      "deploy.sh",
      "REVIEW.md",
    ];
    const files: Record<string, string> = {};
    for (const fn of fileNames) {
      try {
        files[fn] = await fs.readFile(path.join(dir, fn), "utf-8");
      } catch {
        files[fn] = "";
      }
    }

    let envelopesText = "";
    try {
      envelopesText = await fs.readFile(
        path.join(dir, "envelopes.jsonl"),
        "utf-8",
      );
    } catch {
      // empty fine
    }
    const envelopes = parseEnvelopesJsonl(envelopesText);
    const roles = buildRoles(files);

    const bundle: Bundle = {
      id: "v32",
      session: "v32_app_1778635046",
      commit: "6340949",
      produced_at: "2026-05-12T21:19:06-04:00",
      summary: {
        vendor_count: 10,
        files_written: roles.filter((r) => r.bytes > 0).length,
        intents: envelopes.filter((e) => e.type === "INTENTION").length,
        app_runs: true,
        app_check: "GET /todos returned 200",
        elapsed_s: 1036.4,
      },
      roles,
      envelopes,
      files,
    };

    return NextResponse.json(bundle);
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : String(err) },
      { status: 500 },
    );
  }
}
