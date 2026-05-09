# GitHub Action

```yaml
- uses: arajgor1/synapse-audit-action@v1
  with:
    trace-path: 'traces/**/*.json'
    pr-comment: 'true'
    fail-on-conflict: 'false'
```

Posts a PR comment with conflict count + per-trace summary. Uploads an HTML report as a workflow artifact.

See `launch/gh-action/example-workflow.yml` for the full workflow.
