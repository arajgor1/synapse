"""``synapse audit`` — read-only conflict report on existing trace exports.

Usage:
    synapse audit ./langsmith-export.json
    synapse audit ./traces.jsonl --lookback 30
    synapse audit ./otel-spans.json --html ./report.html --json ./report.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from synapse.audit import audit_traces


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="synapse audit",
        description=(
            "Read-only conflict detection on existing agent-framework trace exports. "
            "Supports OpenInference OTel JSON, LangSmith JSON exports, and generic JSONL."
        ),
    )
    p.add_argument("path", help="Path to the trace file (.json, .jsonl, .ndjson)")
    p.add_argument(
        "--lookback",
        type=int,
        default=60,
        help="Stale-base-overwrite window in seconds (default: 60).",
    )
    p.add_argument(
        "--include-reads",
        action="store_true",
        help="Include read-class tool calls (default: write-only — reads can't collide).",
    )
    p.add_argument(
        "--html",
        metavar="OUT",
        help=(
            "Write HTML report to this path (default: ./synapse-audit-<timestamp>.html). "
            "Pass empty string to skip."
        ),
    )
    p.add_argument(
        "--json",
        metavar="OUT",
        help="Write machine-readable JSON report to this path.",
    )
    p.add_argument(
        "--no-summary",
        action="store_true",
        help="Skip the textual summary (only write output files).",
    )

    args = p.parse_args(argv)

    if not Path(args.path).exists():
        print(f"error: trace file not found: {args.path}", file=sys.stderr)
        return 2

    try:
        report = audit_traces(
            args.path,
            lookback_ms=args.lookback * 1000,
            write_only=not args.include_reads,
        )
    except Exception as e:
        print(f"error: failed to audit {args.path}: {e}", file=sys.stderr)
        return 1

    if not args.no_summary:
        report.print_summary()

    # Default HTML output if not suppressed
    html_out = args.html
    if html_out is None:
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        html_out = f"./synapse-audit-{ts}.html"
    if html_out:
        report.write_html(html_out)
        print(f"  HTML report -> {html_out}")

    if args.json:
        report.write_json(args.json)
        print(f"  JSON report -> {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
