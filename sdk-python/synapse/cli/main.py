"""`synapse` CLI entry point.

Subcommands:
- `synapse spec validate [PATH ...]` — validate messages/envelopes against the
  v1.0 schemas. Reads from files or stdin (one JSON object per line).
- `synapse bench --backend NAME [--workload WORKLOAD]` — run the standardized
  benchmark suite against a backend.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any


def cmd_spec_validate(args: argparse.Namespace) -> int:
    from synapse.cli.spec_validate import run_validate

    return run_validate(paths=args.paths, json_lines=args.jsonl)


def cmd_bench(args: argparse.Namespace) -> int:
    from synapse.cli.bench import run_bench

    return asyncio.run(
        run_bench(
            backend=args.backend,
            workload=args.workload,
            output_dir=args.output_dir,
            max_signals=args.max_signals,
        )
    )


def cmd_up(args: argparse.Namespace) -> int:
    from synapse.cli.up import cmd_up as _up
    return _up(args)


def cmd_down(args: argparse.Namespace) -> int:
    from synapse.cli.up import cmd_down as _down
    return _down(args)


def cmd_status(args: argparse.Namespace) -> int:
    from synapse.cli.up import cmd_status as _status
    return _status(args)


def cmd_demo(args: argparse.Namespace) -> int:
    from synapse.cli.demo import main as demo_main
    return demo_main([])


def cmd_audit(args: argparse.Namespace) -> int:
    from synapse.cli.audit import main as audit_main

    audit_argv = [args.path]
    if args.lookback is not None:
        audit_argv += ["--lookback", str(args.lookback)]
    if args.include_reads:
        audit_argv += ["--include-reads"]
    if args.html is not None:
        audit_argv += ["--html", args.html]
    if args.json_out is not None:
        audit_argv += ["--json", args.json_out]
    if args.no_summary:
        audit_argv += ["--no-summary"]
    return audit_main(audit_argv)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="synapse")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # spec
    p_spec = sub.add_parser("spec", help="Protocol spec utilities")
    spec_sub = p_spec.add_subparsers(dest="spec_cmd", required=True)
    p_spec_validate = spec_sub.add_parser(
        "validate",
        help="Validate one or more JSON envelopes against the v1.0 schemas",
    )
    p_spec_validate.add_argument(
        "paths",
        nargs="*",
        help="Files containing JSON envelopes. If empty and not --jsonl, "
        "reads a single JSON object from stdin.",
    )
    p_spec_validate.add_argument(
        "--jsonl",
        action="store_true",
        help="Treat each line of input as a separate JSON envelope (NDJSON).",
    )
    p_spec_validate.set_defaults(func=cmd_spec_validate)

    # bench
    p_bench = sub.add_parser("bench", help="Run the standardized backend benchmark")
    p_bench.add_argument(
        "--backend",
        required=True,
        choices=["mock", "anthropic", "gemini", "openai", "ollama", "vllm-modal"],
        help="Inference adapter to benchmark",
    )
    p_bench.add_argument(
        "--workload",
        default="conflict-heavy",
        choices=["pair-coding", "parallel-research", "conflict-heavy"],
        help="Standardized scenario to run",
    )
    p_bench.add_argument(
        "--max-signals",
        type=int,
        default=10,
        help="Cap signals per run (cost discipline)",
    )
    p_bench.add_argument(
        "--output-dir",
        default="bench/results",
        help="Where to write the results JSON file",
    )
    p_bench.set_defaults(func=cmd_bench)

    # audit
    p_audit = sub.add_parser(
        "audit",
        help=(
            "Read-only conflict detection on existing trace exports "
            "(OpenInference OTel, LangSmith, JSONL)."
        ),
    )
    p_audit.add_argument("path", help="Trace file (.json, .jsonl, .ndjson)")
    p_audit.add_argument(
        "--lookback", type=int, default=60,
        help="Stale-base-overwrite window in seconds (default: 60)",
    )
    p_audit.add_argument(
        "--include-reads", action="store_true",
        help="Include read-class tool calls (default: write-only)",
    )
    p_audit.add_argument(
        "--html", metavar="OUT", default=None,
        help="Write HTML report (default: ./synapse-audit-<ts>.html)",
    )
    p_audit.add_argument(
        "--json", metavar="OUT", dest="json_out", default=None,
        help="Write machine-readable JSON report",
    )
    p_audit.add_argument(
        "--no-summary", action="store_true",
        help="Skip the textual summary",
    )
    p_audit.set_defaults(func=cmd_audit)

    # up
    p_up = sub.add_parser(
        "up",
        help="Bring up the local Synapse stack (Redis + Postgres) via Docker Compose.",
    )
    p_up.add_argument("--services", nargs="+", default=None,
                       help="Subset of services to start (default: all)")
    p_up.add_argument("--timeout", type=int, default=30,
                       help="Health-check timeout in seconds (default: 30)")
    p_up.set_defaults(func=cmd_up)

    # down
    p_down = sub.add_parser("down", help="Stop the local Synapse stack.")
    p_down.add_argument("--volumes", action="store_true",
                         help="Also remove volumes (wipes Redis + Postgres data)")
    p_down.set_defaults(func=cmd_down)

    # status
    p_status = sub.add_parser("status", help="Show Synapse stack status + relevant env vars.")
    p_status.set_defaults(func=cmd_status)

    # demo
    p_demo = sub.add_parser(
        "demo",
        help="Run a local multi-agent demo against the running Synapse stack.",
    )
    p_demo.set_defaults(func=cmd_demo)

    # watch — one-shot live dashboard, no infra needed
    from synapse.cli.watch import add_subparser as add_watch_subparser
    add_watch_subparser(sub)

    # api — REST API surface for non-Python agents
    p_api = sub.add_parser(
        "api",
        help=(
            "Start the Synapse REST API on FastAPI. Lets non-Python agents "
            "(Aider, Goose, Zed, GitHub Copilot extensions, ...) participate "
            "in cross-agent coordination over HTTP."
        ),
    )
    p_api.add_argument(
        "--bind", default="127.0.0.1",
        help=(
            "Host to bind to (default 127.0.0.1, localhost only). "
            "--bind 0.0.0.0 exposes on the LAN -- anyone on the network can "
            "read or claim coordination state, only do this for trusted demos."
        ),
    )
    p_api.add_argument("--port", type=int, default=8000)
    p_api.add_argument("--log-level", default="info")
    p_api.set_defaults(func=lambda args: _cmd_api(args))

    ns = parser.parse_args(argv)
    return int(ns.func(ns))


def _cmd_api(args) -> int:
    try:
        from synapse.api.server import serve
    except ImportError as e:
        print(f"synapse api: missing dependency -- {e}", file=sys.stderr)
        print("Install with: pip install 'synapse-protocol[gateway]'", file=sys.stderr)
        return 2
    serve(host=args.bind, port=args.port, log_level=args.log_level)
    return 0


if __name__ == "__main__":
    sys.exit(main())
