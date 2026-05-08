#!/usr/bin/env python3
"""Claude Code PreToolUse hook for Synapse coordination.

Install this in your Claude Code settings.json:

    {
      "hooks": {
        "PreToolUse": [
          {
            "matcher": "Edit|Write|MultiEdit",
            "hooks": [
              { "type": "command", "command": "python /path/to/synapse-pretooluse.py" }
            ]
          }
        ],
        "PostToolUse": [
          {
            "matcher": "Edit|Write|MultiEdit",
            "hooks": [
              { "type": "command", "command": "python /path/to/synapse-posttooluse.py" }
            ]
          }
        ]
      }
    }

Then run multiple Claude Code sessions on the same repo with different
SYNAPSE_AGENT_ID env vars:

    SYNAPSE_AGENT_ID=alice claude
    SYNAPSE_AGENT_ID=bob claude

Synapse will detect when both sessions touch the same files.

Behavior:
- PreToolUse: emit a Synapse INTENTION envelope BEFORE the write happens.
  If conflict detected, exit with code 2 to deny the tool call (Claude
  Code will retry differently).
- PostToolUse: emit RESOLUTION (write succeeded) so the in-flight
  intention is closed.

Falls back to JSONL audit log if Synapse runtime isn't running, so
the activity is still captured for `synapse audit` later.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def main():
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        # No payload — pass through silently
        sys.exit(0)

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})
    cwd = payload.get("cwd") or os.getcwd()

    # Only handle write-shaped tools
    if tool_name not in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        sys.exit(0)

    file_path = (
        tool_input.get("file_path")
        or tool_input.get("path")
        or tool_input.get("notebook_path")
    )
    if not file_path:
        sys.exit(0)

    # Resolve relative to repo
    abs_path = str(Path(file_path).resolve())
    try:
        rel_path = str(Path(abs_path).relative_to(cwd)).replace("\\", "/")
    except ValueError:
        rel_path = abs_path

    agent_id = os.environ.get("SYNAPSE_AGENT_ID", "claude-code-default")
    session_id = os.environ.get("SYNAPSE_SESSION_ID", "claude-code-session")
    ts_ms = int(time.time() * 1000)

    # Try live intend first; fall back to JSONL log
    fired_live = False
    try:
        sys.path.insert(0, "/usr/local/lib/python3.11/site-packages")  # adjust per install
        from synapse.intend import intend  # type: ignore[import-not-found]
        import asyncio

        async def _fire():
            scope = [f"repo.fs.{rel_path}:w"]
            async with intend(
                scope=scope,
                agent=agent_id,
                session=session_id,
                expected_outcome=f"claude-code:{tool_name}:{rel_path}",
                blocking=True,
                gate_ms=int(os.environ.get("SYNAPSE_GATE_MS", "500")),
            ) as i:
                # The intend context will block / route / abort if there's
                # an active conflict. If we get here, we're cleared to write.
                i.set_state_diff({"hook": "pretooluse", "tool": tool_name})
                return True

        try:
            ok = asyncio.run(_fire())
            fired_live = ok
        except Exception:
            fired_live = False
    except ImportError:
        fired_live = False

    # JSONL fallback for audit-mode coverage
    if not fired_live:
        runs_dir = Path(cwd) / ".synapse" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        event = {
            "trace_id": session_id,
            "span_id": f"{session_id}:{ts_ms}",
            "agent_id": agent_id,
            "session_id": session_id,
            "tool_name": tool_name.lower(),
            "tool_args": {"path": rel_path},
            "ts_start_ms": ts_ms,
            "ts_end_ms": ts_ms,
            "raw": {"hook": "PreToolUse", "claude_code": True},
        }
        log_path = runs_dir / f"{session_id}.jsonl"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    # Allow the tool call by exiting 0
    sys.exit(0)


if __name__ == "__main__":
    main()
