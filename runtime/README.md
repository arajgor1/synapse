# runtime

Runtime services that make Synapse work end-to-end:

| Subdir | What | Status |
|---|---|---|
| `gateway/` | REST + WebSocket gateway exposing the session log to UIs and external agents | ✅ shipped |
| `router/` | L1 (rules) + L2 (SQL) + L3 (semantic) conflict-detection router | ✅ shipped |
| `coordinator/` | BELIEF divergence detection, scope inference, auto-merge orchestration | ✅ shipped |
| `cli/` | `synapse audit` / `synapse watch` / `synapse up` / `synapse install` | ✅ shipped |
| `mcp/` | MCP server exposing 5 tools to external agents | ✅ shipped |
| `modal/` | Bench payloads + Modal sandbox infrastructure (used to produce [`bench/PUBLIC_BENCHMARK.md`](../bench/PUBLIC_BENCHMARK.md) results) | ✅ shipped |

For the current roadmap, see [`docs/roadmap/README.md`](../docs/roadmap/README.md).
