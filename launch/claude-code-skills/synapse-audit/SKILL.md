---
name: synapse-audit
description: Audit existing agent trace exports (LangSmith, OpenInference / OTel, AWS Bedrock, GCP Vertex, Azure AI, plain JSONL) for silent cross-agent collisions. Use when the user has a trace file and wants to find conflicts post-hoc.
---

# /synapse-audit

Run `synapse audit` on a trace export to find silent cross-agent
collisions. Zero infrastructure required — Synapse parses the file
in-memory and prints a conflict report.

## When to invoke

Trigger when the user:

- Says "audit this trace", "check for conflicts", "find collisions in
  my agent run".
- Hands you a `.json` / `.jsonl` / `.ndjson` file from LangSmith, an
  OpenInference exporter, AWS Bedrock Agents, GCP Vertex Agent Builder,
  Azure AI Agent Service, or any structured agent trace.
- Asks "did my agents step on each other?"

Do NOT invoke for live coordination — use `/synapse-watch` for that.

## How to run

```bash
pip install synapse-protocol  # if not already
synapse audit <path-to-trace>
```

Optional flags:

- `--lookback 60` — seconds for stale-base-overwrite detection (default 60).
- `--include-reads` — include read-class tool calls (default: write-only).
- `--html out.html` — also generate an HTML report.
- `--json out.json` — emit machine-readable JSON.

## What the user sees

```
Synapse audit · trace.jsonl
─────────────────────────────────
  total events     : 247
  write events     : 142
  total sessions   : 3
  total conflicts  : 4
  conflict kinds   : scope_overlap=3, stale_base_overwrite=1
  resolution tiers : capability=2, temporal=1, escalation=1

Conflict 1/4
  scope            : repo.fs.app/auth.py:w
  agent (intent)   : alice
  conflicting      : bob (alice's write was active when bob arrived)
  rationale        : ...
```

If the file isn't a recognised format, Synapse auto-detects from
content; the supported list is at
`synapse audit --list-formats` or via the MCP tool
`list_supported_trace_formats`.

## Common pitfalls

- **The user's trace is from a custom format we don't auto-detect.** Ask
  them to convert to JSONL (one event per line) with the fields:
  `agent_id, session_id, tool_name, tool_args, ts_start_ms, ts_end_ms`.
- **`write events: 0`.** The trace has no tool calls Synapse classifies
  as writes. Try `--include-reads`.
- **Postgres-only state graph errors.** `synapse audit` does NOT need
  Postgres or Redis — it's purely file-based. Errors mentioning asyncpg
  mean the user accidentally launched `synapse watch` instead.

## Related

- `/synapse-watch` — live coordination dashboard, no trace file needed.
- `/synapse-explain` — explain a single conflict from a prior audit.
