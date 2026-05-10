# Integration verification recipes

How each Synapse surface is verified end-to-end. Mix of automated tests
(in `sdk-python/tests/`) and 5-step manual recipes for things only a
human can run (loading IDE configs, opening browsers, etc.).

This complements `launch/ide-plugins/MANUAL_VERIFICATION.md` (which
covers the IDE plugin recipes) by documenting verification of the
non-IDE surfaces: REST API, MCP server, Claude Code skills, the
streaming dashboard, and the live `synapse watch` flow.

## REST API (`synapse api`)

**Automated test coverage** (`tests/test_api_rest.py`, 12 tests):
- Health, version, frameworks-list endpoints
- POST /v1/intent (no conflict)
- POST /v1/intent (two-agent collision — both via HTTP)
- POST /v1/intent/{id}/resolve
- GET /v1/sessions/{id}/intentions
- POST /v1/beliefs (with divergence)
- POST /v1/audit/jsonl (real conflict report)
- 400 on empty body, 404 on missing path
- /openapi.json renders correctly

**Manual smoke** (5 minutes):

```
1. pip install 'synapse-protocol[gateway]'
2. synapse api --port 8000          # localhost-only by default
3. Open http://localhost:8000/docs in a browser
   → Swagger UI loads, you can click any endpoint and "Try it out"
4. From a second terminal:
   curl http://localhost:8000/health
   → {"status":"ok","uptime_s":...}
5. Try a 2-agent collision via curl:
   ID=$(curl -sX POST localhost:8000/v1/intent \
     -H 'content-type: application/json' \
     -d '{"scope":["repo.fs.curl_test:w"],"agent":"alice","session":"x","blocking":false}' \
     | python -c "import json,sys;print(json.load(sys.stdin)['intention_id'])")
   curl -X POST localhost:8000/v1/intent \
     -H 'content-type: application/json' \
     -d '{"scope":["repo.fs.curl_test:w"],"agent":"bob","session":"x","blocking":true,"gate_ms":200}'
   → has_conflicts=true; conflicts contain alice
   curl -X POST localhost:8000/v1/intent/$ID/resolve -d '{"outcome":"success"}'
```

If step 3 (Swagger UI loads) AND step 5 (bob sees CONFLICT) both work,
the REST API is verified for any HTTP-speaking client.

## MCP server (`synapse-mcp`)

**Automated test coverage** (`tests/test_mcp_real_client.py`, 4 tests):
Uses the official `mcp` Python package as a real client (the same
library Claude Desktop / Cursor / Continue / Cline all use under the
hood):

- initialize → tools/list (full handshake, all 5 tools enumerated)
- tools/call on `list_supported_trace_formats` (no-arg path)
- tools/call on `audit_trace_file` with a real JSONL conflict file
  → confirms ≥1 conflict surfaces in the response
- tools/call on `does_not_exist` → structured error, connection survives

**Manual smoke** (Claude Desktop, 3 minutes):

```
1. pip install synapse-protocol
2. Edit your claude_desktop_config.json:
     { "mcpServers": { "synapse": { "command": "synapse-mcp" } } }
3. Restart Claude Desktop
4. In a chat, click the "🔨 tools" icon
   → "synapse" appears with 5 tools listed
5. Ask: "Use the synapse list_supported_trace_formats tool"
   → Claude calls the tool and shows the formats
```

## Claude Code skills + sub-agent

**Automated test coverage** (`tests/test_claude_code_artifacts.py`, 13 tests):
- All 5 skills present + valid YAML frontmatter
- Each skill description >40 chars (substantive)
- Each skill references a real Synapse v0.2.x entry point (no stale doc)
- synapse-coordinator agent has frontmatter + canonical surface
- Cross-references between skills resolve

**Manual smoke** (Claude Code, 5 minutes):

```
1. cp -r launch/claude-code-skills/synapse-* ~/.claude/skills/
   cp launch/claude-code-agents/synapse-coordinator.md ~/.claude/agents/
2. Open Claude Code in any project
3. Type: /synapse-watch
   → Skill fires, runs `synapse watch --session demo`, opens browser tab
4. Type: /synapse-audit ./some-trace.jsonl
   → Skill fires, runs the audit command, shows conflict report
5. Ask Claude: "What MergePolicy should I use for billing scopes?"
   → Claude routes to synapse-coordinator agent, recommends
     escalate_to_human + critical_scopes=["billing.*"]
```

## `synapse watch` live coordination dashboard

**Automated test coverage** (`tests/test_cli_watch.py`, 4 tests):
- CLI subcommand registers and parses
- `synapse watch --once 1.5 --no-browser` brings up streaming + dashboard
  servers on bindable ports, dashboard HTML returns 200
- WS port substituted into dashboard HTML correctly
- JSONL audit log written when SYNAPSE_AUDIT_LOG is set

**Manual smoke** (zero-infra, 60 seconds):

```
1. pip install synapse-protocol
2. synapse watch --session demo
   → CLI prints session/audit-log/websocket/dashboard URLs
   → Browser tab auto-opens to http://localhost:8766/
   → Dashboard shows "live" connection state in top-right corner
3. In a second terminal in the same project:
   cd examples/crewai-marketing
   SYNAPSE_SESSION_ID=demo python crew.py
4. Watch the dashboard:
   → 3 events tick up (Researcher, Writer, Editor)
   → 1 conflict tick (Editor pivoting on post.md)
   → 3 distinct agents (researcher, writer, editor) listed
5. Ctrl-C the watch process
   → Banner prints "shutting down…"; ports released cleanly
```

## OpenClaw integration (`@synapse-protocol/sdk` TypeScript SDK)

**Automated test coverage** (`sdk-typescript/src/frameworks/openclaw.test.ts`, 12 tests):
- write tool routing through `intendWith`
- read tool bypass (no overhead)
- multi-tool scope inference
- failure marking on tool errors
- auto_merge policy path
- redirect / abort / wait policies through wrapped tools

**End-to-end real-LLM test** (Modal):

```
modal run runtime/modal/framework_sandbox.py::real_product_dev_openclaw
```

Runs 3 OpenClaw extensions (`dev_a`, `dev_b`, `dev_c`) wrapped with
Synapse, all writing to the same `src/utils/dedupe.py`, real Anthropic
Haiku 4.5 generates each agent's content. Verifies CONFLICTs route
correctly through the live router.

**Manual smoke** (5 minutes — requires Node + an OpenClaw checkout):

```
1. cd path/to/your/openclaw
2. npm install file:/path/to/synapse/sdk-typescript
3. Edit your extension's plugin-registration.ts:
   import { wrapExtensionWithSynapse, Bus } from "@synapse-protocol/sdk";
   const bus = new Bus({ url: process.env.SYNAPSE_REDIS_URL });
   export const wrapped = wrapExtensionWithSynapse(yourExt, { bus, ... });
4. Run two openclaw instances against the same Redis URL with different
   SYNAPSE_AGENT_ID values
5. Trigger overlapping-scope tool calls from both
   → Second arriver's tool dispatch returns has_conflicts=true via the
     wrapped tool result
```

See `launch/ide-plugins/openclaw/README.md` for the full integration recipe.

## Audit pipeline (`synapse audit`)

**Automated test coverage** (`sdk-python/tests/test_audit_*.py`, ~50+ tests):
- Importer for OpenInference, LangSmith, Bedrock, Vertex, Azure, JSONL
- Conflict detector (scope_overlap, stale_base_overwrite, causal_violation)
- SAS drift score
- Resolution-tier hint inference
- AgenticFlict benchmark (5,408 paired PRs, F1=0.865)

**Manual smoke** (30 seconds):

```
1. pip install synapse-protocol
2. synapse audit ./some-trace.jsonl --html out.html
   → Stdout: conflict report
   → out.html: visual report with all conflicts highlighted
```

## Reporting

If any of these fail in your environment, open an issue at
<https://github.com/arajgor1/synapse/issues> with:

- Which surface failed (REST, MCP, skill, watch, OpenClaw, audit)
- The exact step that failed
- Your OS + Python + (where relevant) Node version
- Any error in the relevant log
