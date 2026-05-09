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

# Directory names whose entire subtree is ignored. Matched component-wise
# (so "package.git/foo" is NOT a false positive for ".git").
_IGNORE_DIRS = frozenset({
    ".git", ".idea", ".vscode", "node_modules", "dist", "build",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", ".venv", "venv", "env", ".env",
    "target", "vendor", ".next", ".nuxt", ".turbo",
    # CRITICAL: ignore our own audit log directory or we re-detect our
    # own writes in an infinite loop.
    ".synapse",
})

# Filename extensions/markers always ignored.
_IGNORE_FILE_SUFFIXES = (".swp", ".swo", ".tmp", ".lock", ".log", ".pyc", ".pyo")
_IGNORE_FILE_NAMES = frozenset({".DS_Store", "Thumbs.db", "coverage.xml", "4913"})  # 4913 = vim atomic-write probe
_IGNORE_FILE_PREFIXES = (".#", "#", "~$")  # editor temp files


def _should_ignore(rel_path: str) -> bool:
    """Component-aware ignore check. `rel_path` is forward-slash-normalised."""
    parts = rel_path.split("/")
    # Any directory component matches an ignored dir name?
    for p in parts[:-1]:  # exclude the leaf (filename)
        if p in _IGNORE_DIRS:
            return True
    name = parts[-1]
    if name in _IGNORE_FILE_NAMES:
        return True
    if any(name.endswith(suf) for suf in _IGNORE_FILE_SUFFIXES):
        return True
    if any(name.startswith(pfx) for pfx in _IGNORE_FILE_PREFIXES):
        return True
    if name.endswith("~"):
        return True
    return False


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

    def _scan_stats(self) -> dict[str, tuple[int, int]]:
        """Cheap stat-only scan: rel_path -> (mtime_ns, size_bytes).

        Avoids the per-poll DoS of reading every file. Only files whose
        (mtime, size) signature changes get hashed in `_diff_and_hash`.
        """
        out: dict[str, tuple[int, int]] = {}
        for path in self.root.rglob("*"):
            try:
                rel = str(path.relative_to(self.root)).replace("\\", "/")
            except ValueError:
                continue
            if _should_ignore(rel):
                continue
            try:
                st = path.stat()
            except (PermissionError, OSError, FileNotFoundError):
                continue
            # Filter to regular files (skip dirs/symlinks/devices)
            from stat import S_ISREG
            if not S_ISREG(st.st_mode):
                continue
            out[rel] = (st.st_mtime_ns, st.st_size)
        return out

    def _hash_one(self, rel: str) -> Optional[str]:
        try:
            return _hash_content((self.root / rel).read_bytes())
        except (PermissionError, OSError, FileNotFoundError):
            return None

    def _loop(self):
        # Initial baseline (stat + hash for everything once) so we don't
        # fire on existing files.
        baseline_stats = self._scan_stats()
        self._stat_snapshot: dict[str, tuple[int, int]] = baseline_stats
        # Hash baseline content once so changes-without-mtime-change still
        # get detected on first real change.
        self._snapshot = {}
        for rel in baseline_stats:
            h = self._hash_one(rel)
            if h is not None:
                self._snapshot[rel] = h
        logger.info("fs_watcher: baseline %d files in %s", len(self._snapshot), self.root)

        while not self._stop.is_set():
            time.sleep(self.poll_interval_s)
            current_stats = self._scan_stats()
            ts_ms = int(time.time() * 1000)

            # Only hash files whose (mtime, size) changed OR are new
            for rel, sig in current_stats.items():
                prev_sig = self._stat_snapshot.get(rel)
                if prev_sig == sig:
                    continue  # cheap skip, no read
                h = self._hash_one(rel)
                if h is None:
                    continue
                if rel not in self._snapshot or self._snapshot[rel] != h:
                    self.emit_callback(
                        str(self.root / rel),
                        h,
                        self.agent_id,
                        self.session_id,
                        ts_ms,
                    )
                    self._writes_emitted += 1
                self._snapshot[rel] = h

            # Drop deleted files from snapshot so re-creates fire again
            for rel in list(self._snapshot.keys()):
                if rel not in current_stats:
                    self._snapshot.pop(rel, None)
            self._stat_snapshot = current_stats

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
