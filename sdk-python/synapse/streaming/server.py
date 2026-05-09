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

def _tail_jsonl(path: Path, from_offset: int = 0):
    """Generator yielding (offset, parsed_line) for new lines appended."""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        f.seek(from_offset)
        while True:
            line = f.readline()
            if not line:
                yield (f.tell(), None)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                yield (f.tell(), json.loads(line))
            except json.JSONDecodeError:
                continue


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
        with self._lock:
            dropped = []
            for c in self.clients:
                if not _ws_send_text(c, text):
                    dropped.append(c)
            for c in dropped:
                try: c.close()
                except Exception: pass
                self.clients.remove(c)

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

        offset = 0
        for new_offset, ev in _tail_jsonl(self.watch_path):
            if self._stop.is_set(): break
            offset = new_offset
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

            # Run quick conflict check on the rolling window
            try:
                from synapse.audit import audit_traces
                rep = audit_traces(str(self.watch_path), lookback_ms=10 * 60 * 1000)
                # Push only NEW conflicts (deduped by intention span_id)
                for c in rep.conflicts:
                    cid = f"{c.intention.span_id}:{','.join(c.overlapping_scopes)}"
                    if cid in self._seen_event_ids:
                        continue
                    self._seen_event_ids.add(cid)
                    self.broadcast({
                        "type": "conflict",
                        "kind": c.kind,
                        "scopes": c.overlapping_scopes,
                        "intention_agent": c.intention.agent_id,
                        "conflicting_agents": [x.agent_id for x in c.conflicting],
                        "tier": c.resolution_tier_hint,
                        "rationale": c.rationale,
                        "ts_ms": c.intention.ts_start_ms,
                    })
            except Exception as e:
                # Audit error is non-fatal for streaming
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
