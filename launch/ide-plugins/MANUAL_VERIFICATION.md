# IDE plugin manual verification recipes

**Honest scope statement.** The Synapse test suite (`tests/test_ide_plugins_smoke.py` + `tests/test_mcp_real_client.py`) automatically verifies:

- Every plugin directory exists.
- Config JSON files parse + reference the right command.
- The VS Code package.json is a valid extension manifest.
- The `synapse-mcp` stdio server completes a real handshake with the official `mcp` Python client (the same library Claude Desktop / Cursor / Continue / Cline use under the hood).
- The Claude Code PreToolUse hook runs cleanly against a synthetic payload.

What the suite **cannot** automatically verify:

- Cursor, VS Code, Continue, Cline, Windsurf load the config in their actual UI without errors.
- The Synapse extension surfaces commands in the user's VS Code Command Palette.
- Real Claude Code sessions invoke the PreToolUse hook on actual tool dispatches.

**The recipes below are 5-step manual tests for a human (you) to run** before claiming "the plugin works in IDE X." Each takes 2-5 minutes. Anything that fails is a real bug; please open an issue.

> Note on coverage: aider, cline, codex-cli, continue, cursor are all "MCP-config recipes" — they don't ship per-IDE Synapse code. They tell that IDE's MCP-client to launch the same `synapse-mcp` binary. **One MCP server, six MCP-client front-ends.** This is by design — less code to break, one place to fix bugs. VS Code is the exception (it ships an actual extension because VS Code wraps GitHub Copilot agent mode which doesn't speak MCP yet).

---

## Cursor

```
1. pip install synapse-protocol
2. Copy launch/ide-plugins/cursor/mcp.json into your Cursor MCP settings
   (Settings → Cursor Settings → MCP → Import file)
3. Restart Cursor
4. Open the MCP panel — you should see "synapse" with 5 tools
5. In a chat, ask: "Use the synapse list_supported_trace_formats tool"
   → Cursor should call the tool and show the formats list
```

If step 4 shows "synapse" with the right tool count, the integration works.

## Claude Desktop

```
1. pip install synapse-protocol
2. Edit ~/.../claude_desktop_config.json:
     { "mcpServers": { "synapse": { "command": "synapse-mcp" } } }
3. Restart Claude Desktop
4. Open a chat — the hammer icon should now show "synapse" with 5 tools
5. Ask: "Audit the trace at ~/some/trace.jsonl for cross-agent conflicts"
   → Claude calls audit_trace_file via MCP, surfaces the result
```

## Continue

```
1. pip install synapse-protocol continue-dev
2. Edit ~/.continue/config.json — add the same mcpServers block as
   Cursor (synapse-mcp command, no args)
3. Restart Continue
4. Open the Continue panel — synapse tools should be available to the
   model
5. Ask the model to call list_supported_trace_formats
```

## Cline

```
1. Install Cline VS Code extension
2. Open Cline panel → Settings (gear icon) → MCP Servers → Add
3. Server name: synapse · Command: synapse-mcp · Args: (empty)
4. Save → Cline reloads MCP servers
5. Ask Cline to use the synapse tools
```

## Codex CLI (OpenAI)

```
1. pip install synapse-protocol openai-codex
2. Merge launch/ide-plugins/codex-cli/config.json into ~/.codex/config.json
3. Run `codex` in a repo
4. Ask: "Run the synapse audit_trace_file tool on ./trace.jsonl"
5. Codex dispatches via MCP, prints the audit result
```

## Aider

Aider doesn't natively speak MCP yet. Two integration options:

**A. Use the REST API (recommended, v0.2.3+).**
```
1. Run `synapse api --port 8000` in one terminal
2. Configure aider with a custom tool that hits localhost:8000/v1/intent
   for each file edit
3. Aider's edits now coordinate via Synapse without any plugin
```

**B. Wrap aider in a Python harness (advanced).** See
`launch/ide-plugins/aider/README.md`.

## VS Code

```
1. cd launch/ide-plugins/vscode
2. npm install && npm run compile
3. In VS Code: F1 → "Developer: Install Extension from Location" → pick this dir
4. Reload window
5. F1 → "Synapse:" — you should see at least 3 commands listed
6. Run "Synapse: Audit current repo trace" — file picker opens
```

## Reporting

If ANY of these fail in your IDE / OS / version, open an issue at
https://github.com/arajgor1/synapse/issues with:

- IDE name + version
- OS + Python version
- The exact step that failed
- Any error in the IDE's developer console / log
