# Synapse Audit · GitHub Action

Audit your AI-agent trace exports for silent multi-agent conflicts on every PR. Posts a comment with findings; uploads an HTML report as an artifact.

## Why

If you have agents (Claude Code, Cursor agent mode, Devin, internal LangGraph crews, Bedrock Agents, anything else) that produce trace exports during CI runs, this action will scan those traces and flag:

- **Cross-agent file collisions** — two agents writing the same file in the same session
- **Stale-base overwrites** — a second agent overwrites a recently-modified file without seeing the first agent's edit
- **Schema-migration conflicts** — two agents adding columns to the same table

It uses the same logic as the open-source [synapse audit](https://github.com/arajgor1/synapse) CLI. Free, no account, no data leaves your CI runner.

## Quick start

```yaml
name: Audit agent traces
on: [pull_request]

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: arajgor1/synapse-audit-action@v1
        with:
          trace-path: 'traces/*.json'
```

## Inputs

| Input | Default | Description |
|---|---|---|
| `trace-path` | `traces/*.json` | Glob pattern for trace files (json / jsonl / ndjson) |
| `pr-comment` | `true` | Post a PR comment when conflicts are found |
| `fail-on-conflict` | `false` | Fail the action when conflicts are detected (set to `true` to gate merges) |
| `python-version` | `3.11` | Python version |

## Supported trace formats

- OpenInference / OpenTelemetry (LangChain, LlamaIndex, OpenAI SDK, Anthropic SDK, AutoGen)
- LangSmith run exports
- AWS Bedrock Agents (inline `trace` field or OTel export)
- GCP Vertex AI Agent Builder / ADK (Cloud Trace export)
- Azure AI Agent Service (App Insights export)
- Generic JSONL

The action auto-detects the format from the file content.

## Example: gate merges on conflict

```yaml
- uses: arajgor1/synapse-audit-action@v1
  with:
    trace-path: '.synapse/runs/*.jsonl'
    fail-on-conflict: 'true'
```

This blocks the PR from merging if two of your agents stepped on each other's work.

## Live mode

This action does **post-hoc** auditing — it tells you what already collided. To **prevent** collisions in real time, install the live mode:

```bash
pip install synapse-protocol-py[live]
```

```python
import synapse
synapse.install(framework="langgraph")  # or crewai / autogen / etc.
```

See the [live-mode guide](https://github.com/arajgor1/synapse#live-mode).
