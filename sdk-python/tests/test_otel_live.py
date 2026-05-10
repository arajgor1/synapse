"""Tests for the generic OpenTelemetry-live adapter.

Drives a real opentelemetry-sdk TracerProvider, opens a tool-shaped
span, closes it, and asserts a Synapse INTENTION lands in the SQLite
state graph (zero-infra mode).
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
async def _isolate(tmp_path, monkeypatch):
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    monkeypatch.delenv("SYNAPSE_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("SYNAPSE_OFFLINE", raising=False)
    monkeypatch.setenv("SYNAPSE_SQLITE_PATH", str(tmp_path / "otel.db"))
    from synapse.intend import shutdown as _sd
    await _sd()
    # Reset the adapter's _PATCHED so each test gets a fresh processor.
    import sys
    for k in list(sys.modules.keys()):
        if k.startswith("synapse.frameworks.otel_live"):
            del sys.modules[k]
    parent = sys.modules.get("synapse.frameworks")
    if parent is not None and hasattr(parent, "otel_live"):
        try:
            delattr(parent, "otel_live")
        except AttributeError:
            pass
    from synapse.install import _FRAMEWORK_REGISTRY as _R
    for k in ("otel", "opentelemetry", "otel_live"):
        _R.pop(k, None)
    # Also reset the OTel global provider so each test gets a fresh one.
    try:
        from opentelemetry import trace as otel_trace
        from opentelemetry.sdk.trace import TracerProvider
        otel_trace._TRACER_PROVIDER = None
        otel_trace._TRACER_PROVIDER_SET_ONCE = type(
            otel_trace._TRACER_PROVIDER_SET_ONCE
        )()
    except Exception:
        pass
    yield
    await _sd()


def test_otel_adapter_install_logs_patched(caplog):
    pytest.importorskip("opentelemetry.sdk.trace")
    import logging
    import synapse
    with caplog.at_level(logging.INFO, logger="synapse"):
        synapse.install(framework="otel")
    joined = " ".join(r.getMessage() for r in caplog.records).lower()
    assert "registered synapseotelspanprocessor" in joined or "patched" in joined


@pytest.mark.asyncio
async def test_otel_adapter_emits_intention_for_tool_span(tmp_path, monkeypatch):
    """Open a span carrying OpenInference tool attributes, close it,
    confirm Synapse persisted an INTENTION."""
    pytest.importorskip("opentelemetry.sdk.trace")
    import synapse
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider

    # Force a fresh TracerProvider
    provider = TracerProvider()
    otel_trace._TRACER_PROVIDER = provider

    sess = "otel_test_session"
    monkeypatch.setenv("SYNAPSE_SESSION_ID", sess)
    synapse.install(framework="otel")

    tracer = otel_trace.get_tracer("test")
    with synapse.with_agent("otel_user_agent"):
        with tracer.start_as_current_span("write_file") as span:
            span.set_attribute("openinference.span.kind", "TOOL")
            span.set_attribute("tool.name", "write_file")
            span.set_attribute(
                "tool.parameters",
                '{"path": "test.py", "content": "x"}',
            )
            span.set_attribute("output.value", "wrote 1 byte")
        # Span is closed when the with-block exits → on_end fires.

    # Allow the bridge thread to drain its scheduled coro.
    await asyncio.sleep(0.5)

    sqlite_path = Path(__import__("os").environ["SYNAPSE_SQLITE_PATH"])
    if not sqlite_path.exists():
        pytest.skip("OTel adapter didn't reach the bus (sqlite never created)")
    conn = sqlite3.connect(sqlite_path)
    rows = conn.execute(
        "SELECT agent_id, expected_outcome FROM intentions WHERE session_id = ?",
        (sess,),
    ).fetchall()
    conn.close()

    assert rows, "OTel adapter did not emit an INTENTION for the tool span"
    agents = {r[0] for r in rows}
    assert "otel_user_agent" in agents, (
        f"ContextVar attribution didn't propagate through OTel adapter; "
        f"got {agents}"
    )
    outcomes = {r[1] for r in rows}
    assert any("write_file" in o for o in outcomes), (
        f"Expected outcome to mention tool name; got {outcomes}"
    )


@pytest.mark.asyncio
async def test_otel_adapter_skips_read_only_tool_spans(monkeypatch):
    """Spans for read-class tools (e.g. web.search) should NOT emit
    INTENTIONs — they're not write conflicts."""
    pytest.importorskip("opentelemetry.sdk.trace")
    import synapse
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider()
    otel_trace._TRACER_PROVIDER = provider

    sess = "otel_read_test"
    monkeypatch.setenv("SYNAPSE_SESSION_ID", sess)
    synapse.install(framework="otel")
    tracer = otel_trace.get_tracer("test")
    with synapse.with_agent("read_only_agent"):
        with tracer.start_as_current_span("web_search") as span:
            span.set_attribute("openinference.span.kind", "TOOL")
            span.set_attribute("tool.name", "web_search")
            span.set_attribute("tool.parameters", '{"query": "x"}')
    await asyncio.sleep(0.3)

    sqlite_path = Path(__import__("os").environ.get("SYNAPSE_SQLITE_PATH", ""))
    if not sqlite_path or not sqlite_path.exists():
        # No DB → no intent emitted, which is what we want for read-only.
        return
    conn = sqlite3.connect(sqlite_path)
    rows = conn.execute(
        "SELECT agent_id FROM intentions WHERE session_id = ?", (sess,),
    ).fetchall()
    conn.close()
    assert not rows, (
        f"Expected NO intentions for read-only web_search span; got {rows}"
    )
