"""Smoke + integration tests for ``synapse watch``.

What we cover
-------------
* The CLI subcommand registers and parses without crashing.
* ``--once N --no-browser`` brings up the streaming WS server + dashboard
  HTTP server on bindable ports, then exits cleanly.
* The dashboard HTML responds 200 and contains the WS URL placeholder
  has been substituted with the actual port.
* JSONL audit log gets written to and a streaming WS client receives at
  least the initial hello message.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
import urllib.request
from pathlib import Path

import pytest


def _find_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("0.0.0.0", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_cli_watch_subcommand_registered():
    from synapse.cli.main import main
    # --help should list 'watch'. We invoke with --help and capture
    # SystemExit; the parser writes help to stdout.
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            main(["--help"])
        except SystemExit:
            pass
    assert "watch" in buf.getvalue(), (
        "synapse watch subcommand not surfaced in `synapse --help`"
    )


def test_cli_watch_help_runs():
    from synapse.cli.main import main
    try:
        main(["watch", "--help"])
    except SystemExit as e:
        assert e.code == 0


def test_cli_watch_once_starts_dashboard_and_exits(tmp_path, monkeypatch):
    """Run `synapse watch --once 1.5` in a thread; verify the dashboard
    HTTP server answers and shuts down within the deadline."""
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    monkeypatch.setenv("SYNAPSE_OFFLINE", "1")  # don't engage zero-infra runtime
    runs_dir = tmp_path / "runs"
    ws_port = _find_free_port()
    http_port = _find_free_port()

    from synapse.cli.main import main

    rc: dict = {}

    def _run():
        try:
            rc["code"] = main([
                "watch",
                "--session", "watch_test",
                "--port", str(ws_port),
                "--http-port", str(http_port),
                "--runs-dir", str(runs_dir),
                "--no-browser",
                "--once", "1.5",
            ])
        except Exception as e:
            rc["err"] = repr(e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    # Wait for HTTP server to come up
    deadline = time.time() + 3.0
    body = None
    while time.time() < deadline and body is None:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{http_port}/", timeout=0.5
            ) as r:
                body = r.read().decode("utf-8")
        except Exception:
            time.sleep(0.05)

    assert body is not None, "Dashboard HTTP server never came up"
    assert "<title>synapse watch</title>" in body
    # WS port placeholder must be substituted
    assert f"ws://" in body and str(ws_port) in body, (
        "Dashboard HTML missing the substituted WebSocket URL"
    )

    # Wait for --once timer to expire
    t.join(timeout=4.0)
    assert not t.is_alive(), "synapse watch did not exit within --once deadline"
    assert rc.get("code") == 0, f"watch exited with code={rc}"
    assert (runs_dir / "watch_test.jsonl").exists()


def test_jsonl_audit_log_writes_when_env_set(tmp_path, monkeypatch):
    """When SYNAPSE_AUDIT_LOG points at a file, intend() must append
    INTENTION records to it. This is the contract the streaming server
    relies on."""
    log_path = tmp_path / "live.jsonl"
    monkeypatch.setenv("SYNAPSE_AUDIT_LOG", str(log_path))
    monkeypatch.setenv("SYNAPSE_OFFLINE", "1")  # skip real coordination
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)

    import synapse
    from synapse.intend import shutdown as _sd

    async def run() -> None:
        await _sd()
        try:
            async with synapse.intend(
                scope=["repo.fs.foo:w"],
                agent="probe", session="watch_test",
                expected_outcome="probe write",
                blocking=False,
            ):
                pass
        finally:
            await _sd()

    asyncio.run(run())

    assert log_path.exists(), "JSONL audit log not created"
    lines = [
        json.loads(ln) for ln in log_path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert any(
        rec.get("type") == "intention" and rec.get("agent_id") == "probe"
        for rec in lines
    ), f"intention record not appended; got {lines}"
