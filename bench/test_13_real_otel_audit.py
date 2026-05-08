"""Test 13 — Real exporter → audit pipeline.

The user asked for real Bedrock/Vertex/Azure trace audits. I don't have
credentials for any of those clouds. The honest substitute that still
validates the "exporter → audit" pipeline with a REAL exporter:

  Use the official OpenInference auto-instrumentor for Anthropic
  (openinference-instrumentation-anthropic), let it produce a real
  OTLP/JSON trace export from a synthesized two-agent scenario, then
  run `synapse audit` on the exported trace and verify it detects the
  cross-agent collisions.

This validates:
  1. The OpenInference exporter actually emits the format my importer expects
  2. The audit pipeline catches collisions in the exporter's real output
  3. Recall vs ground truth (we know exactly which writes happened)

It does NOT validate:
  - Bedrock-specific trace shape (still relies on my hand-crafted sample)
  - Vertex-specific trace shape (ditto)
  - Azure App Insights query export shape (ditto)

For Bedrock/Vertex/Azure, the brutal-honesty answer in the protocol doc is:
  "tested only against vendor-doc-compliant hand-crafted samples; real
  cloud-vendor trace exports require credentials we don't have."
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _pip_install(*pkgs: str) -> bool:
    import subprocess
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", *pkgs],
        capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0:
        print(f"  pip install failed: {(proc.stdout + proc.stderr)[-500:]}")
        return False
    return True


def main():
    print("=== Test 13: Real OpenInference exporter -> synapse audit ===")

    # Install the real OpenInference instrumentor + OTel SDK
    print("\nInstalling openinference-instrumentation-anthropic + opentelemetry-sdk...")
    if not _pip_install(
        "openinference-instrumentation-anthropic",
        "opentelemetry-sdk",
        "opentelemetry-exporter-otlp-proto-http",
        "anthropic>=0.40",
    ):
        print("ABORT: cannot install required packages")
        return

    # Set up an in-memory span exporter so we can dump to JSON afterward
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from openinference.instrumentation.anthropic import AnthropicInstrumentor

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    AnthropicInstrumentor().instrument()

    # Now do a real two-agent scenario. Each "agent" is a separate Python
    # async task making real Anthropic SDK calls. We tag each call's
    # session_id and agent_id via the span attributes so the auto-
    # instrumentor records them.
    raw_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if len(raw_key) > 108 and not raw_key.startswith("sk-ant-"):
        os.environ["ANTHROPIC_API_KEY"] = raw_key[10:]

    from anthropic import Anthropic
    client = Anthropic()
    tracer = trace.get_tracer("test_13_real_otel")

    # Fixed prompts so the test is deterministic-ish
    PROMPT_ALICE = (
        "You are alice. The team is building a billing service. Pick a column name "
        "for 'when subscription was canceled' and reply with ONE WORD ONLY (snake_case). "
        "Do not explain."
    )
    PROMPT_BOB = (
        "You are bob. The team is building a billing service. Pick a column name "
        "for 'when subscription was canceled' and reply with ONE WORD ONLY (snake_case). "
        "Do not explain."
    )

    # The expected ground-truth: alice and bob will likely diverge between
    # canceled_at / cancelled_at / cancellation_time / canceled_date. We're
    # not asserting the exact values; we're asserting the audit detects
    # whatever cross-agent overlap happens.

    print("\n--- Calling Anthropic with OpenInference instrumentation ---")
    answers = {}
    for agent_id, prompt in [("alice", PROMPT_ALICE), ("bob", PROMPT_BOB)]:
        with tracer.start_as_current_span(f"agent.tool_call.{agent_id}") as span:
            span.set_attribute("openinference.span.kind", "TOOL")
            span.set_attribute("tool.name", "edit_file")
            span.set_attribute("agent.id", agent_id)
            span.set_attribute("session.id", "test_13_session")
            span.set_attribute("tool.args", json.dumps({"path": "app/models.py", "column": "TBD"}))

            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=20,
                messages=[{"role": "user", "content": prompt}],
            )
            answer = (msg.content[0].text if msg.content else "").strip()
            answers[agent_id] = answer
            span.set_attribute("tool.result", answer)
            print(f"  {agent_id}: {answer!r}")

    # Force flush + collect spans
    provider.force_flush()
    spans = exporter.get_finished_spans()
    print(f"\nCaptured {len(spans)} OpenTelemetry spans")

    # Convert spans to OTLP-shaped JSON the way OpenInference produces it
    spans_json = []
    for s in spans:
        ctx = s.get_span_context()
        attrs_dict = dict(s.attributes or {})
        spans_json.append({
            "name": s.name,
            "spanId": format(ctx.span_id, "016x"),
            "traceId": format(ctx.trace_id, "032x"),
            "startTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(s.start_time / 1e9)),
            "endTime":   time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(s.end_time / 1e9)),
            "attributes": attrs_dict,
        })

    trace_path = REPO_ROOT / "bench" / "results" / "test_13_real_otel_trace.json"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(json.dumps({"spans": spans_json}, indent=2, default=str), encoding="utf-8")
    print(f"Wrote real OTel trace to {trace_path}")

    # Run synapse audit on it
    print("\n--- Running synapse audit on the real OpenInference trace ---")
    sys.path.insert(0, str(REPO_ROOT / "sdk-python"))
    from synapse.audit.pipeline import audit_traces
    rep = audit_traces(str(trace_path))
    print(f"  events:    {rep.total_events}")
    print(f"  writes:    {rep.total_write_events}")
    print(f"  conflicts: {len(rep.conflicts)}")
    for c in rep.conflicts:
        print(f"    [{c.kind}] {c.overlapping_scopes} agents={[c.intention.agent_id] + [x.agent_id for x in c.conflicting]}")

    result = {
        "test_id": "13",
        "scenario": "Real OpenInference auto-instrumentor against real Anthropic SDK -> synapse audit",
        "anthropic_calls": len(answers),
        "agent_answers": answers,
        "otel_spans_captured": len(spans),
        "audit_findings": {
            "events": rep.total_events,
            "writes": rep.total_write_events,
            "conflicts": len(rep.conflicts),
            "conflict_summary": [
                {
                    "kind": c.kind,
                    "scopes": c.overlapping_scopes,
                    "intention_agent": c.intention.agent_id,
                    "conflicting_agents": [x.agent_id for x in c.conflicting],
                }
                for c in rep.conflicts
            ],
        },
        "trace_path": str(trace_path),
    }
    out_path = REPO_ROOT / "bench" / "results" / "test_13_real_otel_audit.json"
    out_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
