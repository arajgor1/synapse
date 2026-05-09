# `synapse audit` CLI

```
synapse audit PATH [OPTIONS]
```

Read-only conflict detection on agent trace exports.

| Option | Default | Description |
|---|---|---|
| `--lookback SECONDS` | 60 | Stale-base-overwrite window |
| `--include-reads` | False | Include read-class tool calls (default: writes only) |
| `--html OUT` | `./synapse-audit-<ts>.html` | HTML report path |
| `--no-html` | False | Suppress the HTML report |
| `--json OUT` | None | Write machine-readable JSON report |
| `--no-summary` | False | Skip the textual summary |

Auto-detected formats: OpenInference / OTel, LangSmith, AWS Bedrock, GCP Vertex, Azure AI Agent, JSONL.
