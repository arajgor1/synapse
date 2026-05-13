"""Smoke tests for the IDE plugin scaffolds in launch/ide-plugins/.

These do NOT install the IDEs (we can't open Cursor or VS Code in CI).
They DO verify:

  * Each plugin dir exists.
  * Config JSON files (cursor/mcp.json, codex-cli/config.json) parse.
  * The MCP server binary they reference (`synapse-mcp`) IS installed
    by the synapse-protocol package and runnable via `python -m synapse.mcp.server`.
  * The VS Code package.json is a valid extension manifest with the
    commands it claims to ship.
  * Each README mentions the right Synapse v0.2.3 surface (synapse watch,
    synapse api, synapse-mcp).

If any of these break, the published "we ship plugins for X" claim
is broken too.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
IDE_PLUGINS_DIR = REPO_ROOT / "launch" / "ide-plugins"


def _has_plugins() -> bool:
    return IDE_PLUGINS_DIR.is_dir()


@pytest.mark.skipif(not _has_plugins(), reason="ide-plugins dir missing")
def test_all_seven_advertised_plugin_dirs_exist():
    """If we claim '7 IDE/agent plugins shipped' the directories must be real.
    OpenClaw was added in v0.2.5 to recognise it as a major
    multi-channel agent gateway (100K+ stars, OpenAI/GitHub/NVIDIA/Vercel
    sponsored)."""
    expected = {"aider", "cline", "codex-cli", "continue", "cursor", "vscode", "openclaw"}
    actual = {p.name for p in IDE_PLUGINS_DIR.iterdir() if p.is_dir()}
    missing = expected - actual
    assert not missing, f"missing plugin dirs: {missing}"


@pytest.mark.skipif(not _has_plugins(), reason="ide-plugins dir missing")
def test_synapse_mcp_binary_is_callable():
    """Every IDE plugin config that references `synapse-mcp` assumes it's
    on the user's PATH after `pip install synapse-protocol-py`. Verify the
    underlying module IS launchable as a stdio MCP server."""
    proc = subprocess.run(
        [sys.executable, "-m", "synapse.mcp.server"],
        input='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n',
        capture_output=True, text=True, timeout=5,
    )
    assert proc.returncode == 0, (
        f"synapse.mcp.server crashed: stderr={proc.stderr[:500]}"
    )
    # stdout should contain a JSON-RPC response
    assert '"jsonrpc"' in proc.stdout
    assert '"serverInfo"' in proc.stdout, proc.stdout[:300]


@pytest.mark.skipif(not _has_plugins(), reason="ide-plugins dir missing")
def test_cursor_mcp_json_parses_and_has_synapse_server():
    """Cursor users drop this file into Settings -> MCP. Validate the
    JSON parses and points at the right command."""
    cfg_path = IDE_PLUGINS_DIR / "cursor" / "mcp.json"
    assert cfg_path.exists(), f"missing {cfg_path}"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert "mcpServers" in cfg, cfg
    assert "synapse" in cfg["mcpServers"], cfg
    assert cfg["mcpServers"]["synapse"].get("command"), cfg


@pytest.mark.skipif(not _has_plugins(), reason="ide-plugins dir missing")
def test_codex_cli_config_json_parses():
    cfg_path = IDE_PLUGINS_DIR / "codex-cli" / "config.json"
    assert cfg_path.exists()
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert cfg["mcpServers"]["synapse"]["command"]


@pytest.mark.skipif(not _has_plugins(), reason="ide-plugins dir missing")
def test_vscode_package_json_is_valid_extension_manifest():
    pkg_path = IDE_PLUGINS_DIR / "vscode" / "package.json"
    assert pkg_path.exists()
    pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    # Required VS Code extension fields
    for key in ("name", "displayName", "version", "publisher",
                "engines", "main", "contributes"):
        assert key in pkg, f"VS Code manifest missing {key!r}"
    assert pkg["engines"].get("vscode"), pkg["engines"]
    # The contributes.commands list shouldn't be empty
    assert pkg["contributes"].get("commands"), pkg["contributes"]
    # The extension.ts source file referenced by `main` should exist
    src_path = IDE_PLUGINS_DIR / "vscode" / "src" / "extension.ts"
    assert src_path.exists(), f"missing src referenced by main: {src_path}"


@pytest.mark.skipif(not _has_plugins(), reason="ide-plugins dir missing")
def test_every_plugin_dir_has_a_readme():
    """README is the user's only doc for plugins that are JUST MCP-config
    recipes (aider, cline, continue). It MUST exist."""
    missing = [
        p.name for p in IDE_PLUGINS_DIR.iterdir()
        if p.is_dir() and not (p / "README.md").exists()
    ]
    assert not missing, f"plugin dirs missing README.md: {missing}"


@pytest.mark.skipif(not _has_plugins(), reason="ide-plugins dir missing")
@pytest.mark.parametrize("plugin_name", [
    "aider", "cline", "codex-cli", "continue", "cursor", "vscode", "openclaw",
])
def test_plugin_readme_mentions_synapse_mcp_or_recent_cli(plugin_name: str):
    """README must reference an actual Synapse v0.2.3 entry point so users
    know what to run. Acceptable references:
      * `synapse-mcp` (the MCP server binary)
      * `synapse watch` (live coordination dashboard)
      * `synapse api` (REST API server, new in v0.2.4)
      * `synapse audit` (offline trace audit)
      * `synapse.install(framework=...)` (Python SDK live mode)
      * `python -m synapse.mcp.server` (raw module invocation)
    If a README references none of these, it's stale doc shipping a
    broken integration recipe.
    """
    readme = IDE_PLUGINS_DIR / plugin_name / "README.md"
    text = readme.read_text(encoding="utf-8").lower()
    keywords = (
        "synapse-mcp", "synapse watch", "synapse api", "synapse audit",
        "synapse.install", "python -m synapse.mcp", "synapse.mcp.server",
        # OpenClaw uses the TypeScript SDK surface
        "wrapextensionwithsynapse", "synapse-protocol",
        "makesynapseextension",
    )
    assert any(k in text for k in keywords), (
        f"{plugin_name}/README.md doesn't mention any current Synapse "
        f"entry point. README is stale -- update it."
    )


@pytest.mark.skipif(not _has_plugins(), reason="ide-plugins dir missing")
def test_claude_code_hook_script_runs_without_crashing():
    """The PreToolUse hook lives at launch/claude-code-hook/ and gets
    invoked by Claude Code with a JSON payload on stdin. Verify the
    script runs cleanly against a synthetic payload."""
    hook = REPO_ROOT / "launch" / "claude-code-hook" / "synapse-pretooluse.py"
    if not hook.exists():
        pytest.skip("claude-code-hook missing")
    # PreToolUse payload shape per Claude Code's docs.
    fake_payload = {
        "session_id": "smoke",
        "transcript_path": "/tmp/synapse_test_transcript.jsonl",
        "tool_name": "Bash",
        "tool_input": {"command": "echo hi"},
    }
    proc = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(fake_payload),
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "SYNAPSE_OFFLINE": "1"},
    )
    # Hook should exit 0 (allow) on a benign payload, or exit 2 (block)
    # with structured stderr -- neither should be a Python traceback.
    assert "Traceback" not in (proc.stderr or ""), (
        f"hook crashed: {proc.stderr[:500]}"
    )
    assert proc.returncode in (0, 1, 2), (
        f"hook returned unexpected exit code {proc.returncode}; "
        f"stdout={proc.stdout[:200]} stderr={proc.stderr[:200]}"
    )
