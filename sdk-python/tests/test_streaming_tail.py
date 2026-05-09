"""Tests for the rotation-aware ``_tail_jsonl`` helper.

The pre-fix tail kept a single open file handle for the lifetime of the
generator. If the upstream JSONL log was rotated (truncated, replaced)
the handle pointed at the stale inode and silently dropped every
subsequent event. These tests exercise both the happy append path and
the rotation/truncation paths.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from synapse.streaming.server import _tail_jsonl


def _writeln(p: Path, obj: dict) -> None:
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj) + "\n")
        f.flush()


def _drain_for(gen, timeout: float, target_count: int) -> list:
    """Pull events from the tail generator until target_count seen or
    timeout expires."""
    out: list = []
    deadline = time.time() + timeout
    while time.time() < deadline and len(out) < target_count:
        try:
            _offset, ev = next(gen)
        except StopIteration:
            break
        if ev is not None:
            out.append(ev)
        else:
            time.sleep(0.05)
    return out


def test_tail_yields_appended_lines(tmp_path: Path):
    log = tmp_path / "stream.jsonl"
    _writeln(log, {"i": 0})

    stop = threading.Event()
    gen = _tail_jsonl(log, stop=stop)

    # Initial line + 2 appended lines
    _writeln(log, {"i": 1})
    _writeln(log, {"i": 2})

    out = _drain_for(gen, timeout=2.0, target_count=3)
    stop.set()
    gen.close()

    assert [e["i"] for e in out] == [0, 1, 2]


def test_tail_recovers_from_truncation(tmp_path: Path):
    """Truncate the file (size shrinks below current offset) — the tail
    should reopen and start reading from the new beginning."""
    log = tmp_path / "stream.jsonl"
    _writeln(log, {"i": 0})

    stop = threading.Event()
    gen = _tail_jsonl(log, stop=stop)

    # Drain the initial line
    out = _drain_for(gen, timeout=1.0, target_count=1)
    assert out == [{"i": 0}]

    # Truncate and append fresh content (mimics log rotation in place)
    with open(log, "w", encoding="utf-8") as f:
        f.write("")
    _writeln(log, {"i": 99})

    more = _drain_for(gen, timeout=3.0, target_count=1)
    stop.set()
    gen.close()

    assert more == [{"i": 99}], (
        f"Tail did not recover from truncation; saw {more}. "
        "The pre-fix behaviour was to silently drop everything written "
        "after rotation."
    )


def test_tail_stops_on_event(tmp_path: Path):
    """``stop`` event must terminate the generator promptly."""
    log = tmp_path / "stream.jsonl"
    _writeln(log, {"i": 0})

    stop = threading.Event()
    gen = _tail_jsonl(log, stop=stop)

    # Drain initial
    _drain_for(gen, timeout=1.0, target_count=1)

    # Set stop, then ensure the next pull returns quickly (StopIteration
    # because the generator returns when stop.is_set()).
    stop.set()
    t0 = time.time()
    seen = []
    try:
        for _offset, ev in gen:
            seen.append(ev)
            if time.time() - t0 > 1.0:
                pytest.fail("tail did not stop within 1s of stop event")
    except StopIteration:
        pass
    assert time.time() - t0 < 1.0
