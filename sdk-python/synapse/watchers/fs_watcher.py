"""Filesystem watcher that emits Synapse INTENTION envelopes on file writes.

For IDE / CLI agents (Cursor, Claude Code, Codex, VS Code Copilot, Aider)
that don't directly call ``synapse.intend()``. Run this watcher in a
sidecar process. Each detected write fires an INTENTION; Synapse's
existing detector raises CONFLICT envelopes when two such writes
overlap on scope.

Usage:
    python -m synapse.watchers.fs_watcher /path/to/repo \\
        --agent-id alice-claude-code \\
        --session multi-dev-session

Or programmatically:
    watcher = FSWatcher(repo_root, agent_id="alice", session_id="...")
    watcher.start()
    ...do agent work...
    watcher.stop()

Reduced-fidelity caveats:
- Sees writes post-fact, not "intent" mid-thinking. Cannot prevent a
  same-instant collision; only logs.
- Cannot extract beliefs (no LLM-output access). Only structural
  (file-overlap) detection.
- File-watcher events from some editors (atomic-write via rename, swap
  files) need special handling — we ignore .swp / .tmp / # patterns.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_IGNORE_PATTERNS = (
    ".swp", ".swo", ".tmp", ".#", "~",
    ".DS_Store", "__pycache__", ".git/", ".idea/",
    ".vscode/", "node_modules/", "dist/", "build/",
    # CRITICAL: ignore our own audit log directory or we re-detect our
    # own writes in an infinite loop.
    ".synapse/",
    # Common test/build outputs that change rapidly without user intent
    ".pytest_cache/", ".mypy_cache/", ".ruff_cache/", "coverage.xml",
)


def _should_ignore(path: str) -> bool:
    return any(p in path for p in _IGNORE_PATTERNS)


def _hash_content(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()[:16]


class FSWatcher:
    """Polls a directory tree for file modifications.

    We use polling rather than `watchdog` because:
      1. Avoids extra dep on the slim install path
      2. Some editors (VS Code, JetBrains) atomic-rename which trips
         watchdog's INotify backend
      3. Polling at 200-500ms is fine for the IDE-agent use case (the
         agent's wall-clock between writes is multi-second)

    Each detected modification fires emit_callback(path, content_hash,
    agent_id, session_id, timestamp_ms).
    """

    def __init__(
        self,
        root: str | Path,
        agent_id: str,
        session_id: str,
        poll_interval_s: float = 0.3,
        emit_callback: Optional[Callable] = None,
    ):
        self.root = Path(root).resolve()
        self.agent_id = agent_id
        self.session_id = session_id
        self.poll_interval_s = poll_interval_s
        self.emit_callback = emit_callback or self._default_emit

        self._snapshot: dict[str, str] = {}  # path -> content hash
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._writes_emitted = 0

    @property
    def writes_emitted(self) -> int:
        return self._writes_emitted

    def _default_emit(
        self,
        path: str,
        content_hash: str,
        agent_id: str,
        session_id: str,
        ts_ms: int,
    ):
        """Default emitter: try to fire a Synapse INTENTION envelope.

        If `synapse.intend` isn't reachable (e.g., Synapse runtime not
        running), fall back to writing a JSONL log line so the audit
        path can pick it up.
        """
        try:
            # Best-effort live emission. We schedule the intend coroutine
            # without awaiting — fire-and-forget for the sidecar use case.
            from synapse.intend import intend as _intend  # noqa: F401

            async def _fire():
                rel = str(Path(path).relative_to(self.root)).replace("\\", "/")
                scope = [f"repo.fs.{rel}:w"]
                async with _intend(
                    scope=scope,
                    agent=agent_id,
                    session=session_id,
                    expected_outcome=f"fs_watcher:write:{rel}",
                    blocking=False,  # post-hoc — don't block the IDE
                    gate_ms=0,
                ) as i:
                    i.set_state_diff({"content_hash": content_hash})

            try:
                loop = asyncio.get_running_loop()
                asyncio.run_coroutine_threadsafe(_fire(), loop)
            except RuntimeError:
                # No running loop in this thread — write a JSONL fallback
                self._write_jsonl_fallback(path, content_hash, agent_id, session_id, ts_ms)
        except Exception as e:
            logger.debug("fs_watcher: live intend failed (%s) — JSONL fallback", e)
            self._write_jsonl_fallback(path, content_hash, agent_id, session_id, ts_ms)

    def _write_jsonl_fallback(
        self, path: str, content_hash: str, agent_id: str, session_id: str, ts_ms: int
    ):
        """Last-resort: append a JSONL event to .synapse/runs/<session>.jsonl
        so `synapse audit` can pick it up later."""
        import json
        runs_dir = self.root / ".synapse" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        log_path = runs_dir / f"{session_id}.jsonl"
        rel = str(Path(path).relative_to(self.root)).replace("\\", "/")
        event = {
            "trace_id": session_id,
            "span_id": f"{session_id}:{ts_ms}",
            "agent_id": agent_id,
            "session_id": session_id,
            "tool_name": "edit_file",
            "tool_args": {"path": rel},
            "ts_start_ms": ts_ms,
            "ts_end_ms": ts_ms,
            "raw": {"content_hash": content_hash, "source": "fs_watcher"},
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    def _scan(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for path in self.root.rglob("*"):
            try:
                rel = str(path.relative_to(self.root)).replace("\\", "/")
            except ValueError:
                continue
            if _should_ignore(rel) or not path.is_file():
                continue
            try:
                content = path.read_bytes()
                out[rel] = _hash_content(content)
            except (PermissionError, OSError):
                continue
        return out

    def _loop(self):
        # Initial baseline — don't fire on existing files
        self._snapshot = self._scan()
        logger.info("fs_watcher: baseline %d files in %s", len(self._snapshot), self.root)

        while not self._stop.is_set():
            time.sleep(self.poll_interval_s)
            current = self._scan()
            ts_ms = int(time.time() * 1000)

            # New files
            for path, h in current.items():
                if path not in self._snapshot or self._snapshot[path] != h:
                    self.emit_callback(
                        str(self.root / path),
                        h,
                        self.agent_id,
                        self.session_id,
                        ts_ms,
                    )
                    self._writes_emitted += 1

            # Note: we ignore deletes for now (they don't collide with writes)
            self._snapshot = current

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name=f"fs-watcher-{self.agent_id}")
        self._thread.start()
        logger.info("fs_watcher: started (agent=%s session=%s)", self.agent_id, self.session_id)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("fs_watcher: stopped (emitted %d writes)", self._writes_emitted)


def watch_directory(
    root: str | Path,
    *,
    agent_id: Optional[str] = None,
    session_id: Optional[str] = None,
    poll_interval_s: float = 0.3,
) -> FSWatcher:
    agent_id = agent_id or os.environ.get("SYNAPSE_AGENT_ID", "fs-watched-agent")
    session_id = session_id or os.environ.get("SYNAPSE_SESSION_ID", "fs-watched-session")
    w = FSWatcher(root, agent_id, session_id, poll_interval_s=poll_interval_s)
    w.start()
    return w


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Synapse FS watcher (IDE-agent integration)")
    ap.add_argument("path", help="Directory to watch")
    ap.add_argument("--agent-id", default=None, help="Synapse agent identity")
    ap.add_argument("--session", default=None, help="Synapse session id")
    ap.add_argument("--poll", type=float, default=0.3, help="Poll interval (seconds)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
    w = watch_directory(args.path, agent_id=args.agent_id, session_id=args.session, poll_interval_s=args.poll)
    print(f"Watching {args.path} as agent={w.agent_id} session={w.session_id}")
    print("Ctrl-C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        w.stop()
        print(f"\nEmitted {w.writes_emitted} write(s).")


if __name__ == "__main__":
    main()
