"""WebSocket server that pushes new CONFLICT events as they appear.

Lightweight (no external WebSocket library) — uses Python's stdlib
`http.server` upgraded via the WebSocket handshake. Sufficient for
single-host dashboards.

For production multi-tenant streaming, switch to `uvicorn + fastapi +
websockets`; this is the slim-install-friendly version.

Usage:
    python -m synapse.streaming.server [--port 8765] [--watch path/to/log.jsonl]

The server tails the JSONL log (default: `.synapse/runs/`) for new
events, re-runs the audit against the rolling window, and pushes any
new conflicts to all connected clients.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import socket
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterable


WS_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
DEFAULT_PORT = 8765


# ---------------------------------------------------------------------------
# Tiny WebSocket implementation (stdlib only, RFC 6455 subset)
# ---------------------------------------------------------------------------

def _ws_handshake(client: socket.socket) -> bool:
    """Read HTTP request, send 101 Switching Protocols if it's a WS upgrade."""
    data = b""
    client.settimeout(2.0)
    while b"\r\n\r\n" not in data:
        chunk = client.recv(2048)
        if not chunk:
            return False
        data += chunk
        if len(data) > 16384:
            return False
    headers: dict[str, str] = {}
    for line in data.split(b"\r\n")[1:]:
        if b":" in line:
            k, _, v = line.decode("latin-1", errors="ignore").partition(":")
            headers[k.strip().lower()] = v.strip()
    key = headers.get("sec-websocket-key")
    if not key or "websocket" not in headers.get("upgrade", "").lower():
        client.send(b"HTTP/1.1 426 Upgrade Required\r\n\r\n")
        return False
    accept = base64.b64encode(hashlib.sha1(key.encode("latin-1") + WS_GUID).digest()).decode()
    client.send((
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
    ).encode("latin-1"))
    client.settimeout(None)
    return True


def _ws_send_text(client: socket.socket, text: str) -> bool:
    payload = text.encode("utf-8")
    n = len(payload)
    header = bytearray([0x81])  # FIN + opcode=1 (text)
    if n < 126:
        header.append(n)
    elif n < (1 << 16):
        header += bytearray([126]) + struct.pack(">H", n)
    else:
        header += bytearray([127]) + struct.pack(">Q", n)
    try:
        client.sendall(bytes(header) + payload)
        return True
    except (OSError, BrokenPipeError):
        return False


# ---------------------------------------------------------------------------
# Tail loop
# ---------------------------------------------------------------------------

def _tail_jsonl(path: Path, from_offset: int = 0, *, stop: threading.Event | None = None):
    """Generator yielding (offset, parsed_line) for new lines appended.

    Robust against:
      * File rotation / truncation (re-open when size shrinks below offset
        or when the underlying inode changes).
      * Idle periods (yields ``(offset, None)`` only between polls; the
        caller still controls cadence via the empty-line sleep).

    The previous implementation opened the file exactly once at start. If
    the JSONL log was rotated or truncated, the handle continued to point
    at the (now stale) inode and silently missed every new event. This
    reopen-on-rotation pattern is the standard ``tail -F`` semantics.
    """
    def _snap_head(fp) -> bytes:
        """Read up to the first 64 bytes of the file without disturbing
        the read position. Used as a content fingerprint to detect
        in-place truncate-then-rewrite rotation that size/inode checks
        miss when the new file quickly grows past the old offset."""
        pos = fp.tell()
        try:
            fp.seek(0)
            return fp.read(64).encode("utf-8", errors="ignore")
        except Exception:
            return b""
        finally:
            try:
                fp.seek(pos)
            except Exception:
                pass

    f = open(path, "r", encoding="utf-8", errors="ignore")
    try:
        f.seek(from_offset)
        try:
            current_inode = os.fstat(f.fileno()).st_ino
        except (AttributeError, OSError):
            current_inode = None  # Windows / non-POSIX
        head_snap = _snap_head(f)

        while True:
            if stop is not None and stop.is_set():
                return
            line = f.readline()
            if not line:
                # No new data — check for rotation/truncation before idling
                try:
                    st = path.stat()
                    pos = f.tell()
                    head_now = _snap_head(f)
                    rotated = (
                        st.st_size < pos
                        # File shrank vs our previous head sample — but
                        # may have grown back. Compare content directly:
                        # if the first 64 bytes of the file no longer
                        # match what we saw on open, rotation happened.
                        or (head_snap and head_now and head_snap != head_now)
                        or (current_inode is not None and st.st_ino != current_inode)
                    )
                except FileNotFoundError:
                    rotated = True
                    st = None
                if rotated:
                    try:
                        f.close()
                    except Exception:
                        pass
                    # Wait briefly for the new file to appear after rotation
                    for _ in range(20):  # up to 2s
                        if path.exists():
                            break
                        if stop is not None and stop.is_set():
                            return
                        time.sleep(0.1)
                    if not path.exists():
                        yield (0, None)
                        continue
                    f = open(path, "r", encoding="utf-8", errors="ignore")
                    try:
                        current_inode = os.fstat(f.fileno()).st_ino
                    except (AttributeError, OSError):
                        current_inode = None
                    head_snap = _snap_head(f)
                    # Start from the beginning of the new file
                    continue
                yield (f.tell(), None)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                yield (f.tell(), json.loads(line))
            except json.JSONDecodeError:
                continue
    finally:
        try:
            f.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class StreamingServer:
    def __init__(self, port: int, watch_path: Path):
        self.port = port
        self.watch_path = watch_path
        self.clients: list[socket.socket] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._seen_event_ids: set[str] = set()

    def broadcast(self, msg: dict) -> None:
        text = json.dumps(msg, default=str)
        # Snapshot under the lock; SEND outside the lock so a slow client
        # cannot block the accept loop. The previous implementation held
        # the lock for the entire send fan-out and used list.remove() in
        # a loop (O(n^2)) to drop dead clients.
        with self._lock:
            snapshot = list(self.clients)
        dropped: set[int] = set()
        for c in snapshot:
            if not _ws_send_text(c, text):
                dropped.add(id(c))
                try: c.close()
                except Exception: pass
        if dropped:
            with self._lock:
                self.clients = [c for c in self.clients if id(c) not in dropped]

    def _accept_loop(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", self.port))
        srv.listen(8)
        srv.settimeout(0.5)
        print(f"[streaming] listening on ws://localhost:{self.port}/", flush=True)
        while not self._stop.is_set():
            try:
                client, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            ok = _ws_handshake(client)
            if ok:
                print(f"[streaming] client connected: {addr}", flush=True)
                # Send initial hello
                _ws_send_text(client, json.dumps({
                    "type": "hello",
                    "server": "synapse-streaming",
                    "version": "0.2.2",
                    "watching": str(self.watch_path),
                }))
                with self._lock:
                    self.clients.append(client)
            else:
                try: client.close()
                except Exception: pass
        srv.close()

    def _watch_loop(self) -> None:
        # Wait for the file to exist
        while not self._stop.is_set():
            if self.watch_path.exists():
                break
            time.sleep(0.5)
        if self._stop.is_set(): return

        # Incremental conflict detector — keeps a rolling window of recent
        # events keyed by scope and only checks the new event against
        # priors that share at least one scope. The previous version
        # re-parsed the entire JSONL log AND re-ran the full audit on
        # every appended line, which was O(N^2) in event count and
        # collapsed the streaming server under any non-toy load.
        from synapse.audit.events import AuditEvent
        from synapse.audit.scope_inference import infer_scope as _infer_scope

        lookback_ms = 10 * 60 * 1000
        # scope -> list[(ts_end_ms, agent_id, span_id, AuditEvent-ish dict)]
        recent_by_scope: dict[str, list[tuple[int, str, str, dict]]] = {}

        def _trim(now_ms: int) -> None:
            cutoff = now_ms - lookback_ms
            for k in list(recent_by_scope.keys()):
                kept = [t for t in recent_by_scope[k] if t[0] >= cutoff]
                if kept:
                    recent_by_scope[k] = kept
                else:
                    del recent_by_scope[k]

        for _new_offset, ev in _tail_jsonl(self.watch_path, stop=self._stop):
            if self._stop.is_set(): break
            if ev is None:
                time.sleep(0.2)
                continue

            # Synthesize a "live event" message
            msg = {
                "type": "event",
                "agent_id": ev.get("agent_id"),
                "session_id": ev.get("session_id"),
                "tool_name": ev.get("tool_name"),
                "tool_args": ev.get("tool_args"),
                "ts_ms": ev.get("ts_start_ms"),
            }
            self.broadcast(msg)

            # ---- Incremental conflict check ----
            try:
                tool_name = ev.get("tool_name") or ""
                tool_args = ev.get("tool_args") or {}
                ts_start = int(ev.get("ts_start_ms") or 0)
                ts_end = int(ev.get("ts_end_ms") or ts_start)
                agent_id = str(ev.get("agent_id") or "unknown")
                span_id = str(ev.get("span_id") or f"{ts_start}:{tool_name}")
                session_id = str(ev.get("session_id") or "default")

                # Build a lightweight AuditEvent stub for scope inference
                stub = AuditEvent(
                    trace_id=str(ev.get("trace_id") or "stream"),
                    span_id=span_id,
                    agent_id=agent_id,
                    session_id=session_id,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    ts_start_ms=ts_start,
                    ts_end_ms=ts_end,
                )
                scopes = _infer_scope(stub) or []
                if not scopes:
                    continue

                _trim(ts_start)

                colliding: list[tuple[str, list[str], str]] = []
                kind: str | None = None
                for scope in scopes:
                    for prior_ts_end, prior_agent, prior_span, prior_meta in recent_by_scope.get(scope, []):
                        if prior_agent == agent_id:
                            continue
                        if prior_ts_end >= ts_start:
                            kind = "scope_overlap"
                        elif ts_start - prior_ts_end <= lookback_ms:
                            kind = kind or "stale_base_overwrite"
                        else:
                            continue
                        colliding.append((prior_agent, [scope], prior_span))

                # Record this event for future collisions
                for scope in scopes:
                    recent_by_scope.setdefault(scope, []).append(
                        (ts_end, agent_id, span_id, {"tool_name": tool_name})
                    )

                if colliding and kind is not None:
                    overlap_scopes = sorted({s for _a, ss, _sp in colliding for s in ss})
                    cid = f"{span_id}:{','.join(overlap_scopes)}"
                    if cid not in self._seen_event_ids:
                        self._seen_event_ids.add(cid)
                        self.broadcast({
                            "type": "conflict",
                            "kind": kind,
                            "scopes": overlap_scopes,
                            "intention_agent": agent_id,
                            "conflicting_agents": sorted({a for a, _ss, _sp in colliding}),
                            "tier": None,  # incremental detector does not infer tier
                            "rationale": "streaming incremental scope-overlap match",
                            "ts_ms": ts_start,
                        })
            except Exception as e:
                # Detection error is non-fatal for streaming
                self.broadcast({"type": "warning", "message": str(e)[:200]})

    def serve_forever(self) -> None:
        a = threading.Thread(target=self._accept_loop, daemon=True, name="ws-accept")
        w = threading.Thread(target=self._watch_loop, daemon=True, name="audit-watch")
        a.start(); w.start()
        try:
            while not self._stop.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            print("[streaming] shutting down", flush=True)
            self._stop.set()


def main() -> None:
    p = argparse.ArgumentParser(prog="synapse.streaming.server")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--watch", default=".synapse/runs/default.jsonl",
                   help="JSONL log to tail. Default .synapse/runs/default.jsonl")
    args = p.parse_args()
    server = StreamingServer(args.port, Path(args.watch))
    server.serve_forever()


if __name__ == "__main__":
    main()
