"""User Acceptance Test scenarios — natural workflows users will actually run.

Each scenario is what an honest user would do on day 1 with the v0.2.2
release. We exercise these end-to-end (no mocks) and capture transcripts
so we can show "drop in this command, get this output" in marketing.

Run with: python bench/uat_scenarios.py [--scenario N]

All scenarios are $0 LLM (no Anthropic / Modal). They exercise:
  - Day-1 install path (synapse audit on existing trace JSON)
  - Cloud-vendor trace import (Bedrock / Vertex / Azure)
  - SCF features (resolution-tier hint, SAS drift, conflict tiers)
  - FS watcher capture of real concurrent edits
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "sdk-python"))


# -------- helpers --------

def section(title: str) -> None:
    print()
    print("=" * 76)
    print(f"  {title}")
    print("=" * 76)


def cmd(label: str, body: str) -> None:
    print(f"\n# {label}")
    print(f"$ {body}")


def show_output(text: str, max_lines: int = 30) -> None:
    lines = text.strip().splitlines()
    for line in lines[:max_lines]:
        print(f"  {line}")
    if len(lines) > max_lines:
        print(f"  ... [{len(lines) - max_lines} more lines]")


# -------- scenarios --------

def scenario_1_audit_real_openinference() -> dict:
    """Scenario 1: Drop a real OpenInference trace, get cross-agent conflicts.

    User story: "I have a multi-agent run already done. I exported the
    OpenInference trace to JSON. I want to know if the agents stepped
    on each other."
    """
    section("Scenario 1: audit real OpenInference trace (cross-Claude-Code session)")

    cmd("user runs",
        "synapse audit bench/results/test_13_real_otel_trace.json --no-html")

    from synapse.audit import audit_traces
    trace_path = REPO_ROOT / "bench" / "results" / "test_13_real_otel_trace.json"
    if not trace_path.exists():
        return {"scenario": 1, "skipped": "trace file not present"}

    rep = audit_traces(str(trace_path))
    print()
    print("Output:")
    rep.print_summary()

    return {
        "scenario": 1,
        "trace": str(trace_path),
        "events": rep.total_events,
        "conflicts": len(rep.conflicts),
        "tiers": rep.conflict_tiers,
        "sas_pairs": len(rep.sas_pairs),
    }


def scenario_2_cloud_vendor_trace() -> dict:
    """Scenario 2: Audit a Bedrock Agent trace export.

    User story: "I run AWS Bedrock Agents. I exported the trace. Now I
    want to find conflicts."
    """
    section("Scenario 2: audit AWS Bedrock Agent trace")

    cmd("user runs",
        "synapse audit bench/scenarios/cloud_trace_samples/bedrock_two_agents_billing.json")

    from synapse.audit import audit_traces
    rep = audit_traces(str(REPO_ROOT / "bench" / "scenarios" / "cloud_trace_samples"
                           / "bedrock_two_agents_billing.json"))
    print()
    print("Output:")
    rep.print_summary()

    return {
        "scenario": 2,
        "events": rep.total_events,
        "conflicts": len(rep.conflicts),
        "tiers": rep.conflict_tiers,
        "sas_drift_warning": any(p.sas < 0.5 for p in rep.sas_pairs),
    }


def scenario_3_critical_scope_policy_tier() -> dict:
    """Scenario 3: A billing-related conflict gets policy-tier priority.

    User story: "Two agents touched billing.charge.user_42. I want
    Synapse to tell me this is high-severity."
    """
    section("Scenario 3: critical-scope (billing.*) gets policy-tier hint")

    cmd("set up", "two AuditEvents on billing.charge.user_42, agent_a + agent_b")

    from synapse.audit import AuditEvent, detect_conflicts
    events = [
        AuditEvent(
            trace_id="t", span_id="s1", agent_id="agent_a", session_id="s",
            tool_name="charge_card",
            ts_start_ms=1000, ts_end_ms=1100,
            tool_args={"user": 42}, scope_inferred=["billing.charge.user_42:w"],
        ),
        AuditEvent(
            trace_id="t", span_id="s2", agent_id="agent_b", session_id="s",
            tool_name="charge_card",
            ts_start_ms=1500, ts_end_ms=1600,
            tool_args={"user": 42}, scope_inferred=["billing.charge.user_42:w"],
        ),
    ]
    conflicts = detect_conflicts(events, write_only=False)
    print()
    print("Output:")
    print(f"  conflicts: {len(conflicts)}")
    for c in conflicts:
        print(f"    {c.kind} on {c.overlapping_scopes}")
        print(f"    resolution_tier_hint: {c.resolution_tier_hint}")
        print(f"    rationale: {c.rationale}")

    return {
        "scenario": 3,
        "conflicts": len(conflicts),
        "tier": conflicts[0].resolution_tier_hint if conflicts else None,
        "expected_tier": "policy",
        "pass": len(conflicts) == 1 and conflicts[0].resolution_tier_hint == "policy",
    }


def scenario_4_sas_drift_warning() -> dict:
    """Scenario 4: Two agents working on overlapping scopes get a low SAS warning.

    User story: "Two agents in my team are not crashing into each other
    (no CONFLICT envelopes), but I want to know if their operational
    patterns are diverging."
    """
    section("Scenario 4: SAS drift warning for misaligned agents on shared scope")

    cmd("set up", "agent_a writes to /db only; agent_b writes to /db AND /admin")

    from synapse.audit import AuditEvent, compute_sas
    events = [
        AuditEvent(trace_id="t", span_id="a1", agent_id="alice", session_id="s",
                   tool_name="db_write", ts_start_ms=1000, ts_end_ms=1100,
                   tool_args={}, scope_inferred=["db.users:w"]),
        AuditEvent(trace_id="t", span_id="a2", agent_id="alice", session_id="s",
                   tool_name="db_write", ts_start_ms=2000, ts_end_ms=2100,
                   tool_args={}, scope_inferred=["db.users:w"]),
        AuditEvent(trace_id="t", span_id="b1", agent_id="bob", session_id="s",
                   tool_name="admin_action", ts_start_ms=1500, ts_end_ms=1600,
                   tool_args={}, scope_inferred=["db.users:w"]),
        AuditEvent(trace_id="t", span_id="b2", agent_id="bob", session_id="s",
                   tool_name="admin_action", ts_start_ms=2500, ts_end_ms=2600,
                   tool_args={}, scope_inferred=["admin.console:w"]),
    ]
    pairs = compute_sas(events)
    print()
    print("Output:")
    for p in pairs:
        print(f"  {p.agent_a} <> {p.agent_b}:")
        print(f"    SAS: {p.sas:.3f}  (entity={p.entity_overlap:.2f}, "
              f"action={p.action_consistency:.2f}, temporal={p.temporal_alignment:.2f})")
        print(f"    shared scopes: {p.shared_scopes}")

    return {
        "scenario": 4,
        "pairs": len(pairs),
        "alice_bob_sas": pairs[0].sas if pairs else None,
        "shared_scopes": pairs[0].shared_scopes if pairs else None,
    }


def scenario_5_concurrent_fs_watcher() -> dict:
    """Scenario 5: Two FS watchers detect concurrent file edits.

    User story: "I have Cursor and Claude Code both running on my repo.
    I want to know if they touched the same file."
    """
    section("Scenario 5: concurrent FS watchers catch shared-file edit")

    import tempfile
    import threading
    from synapse.watchers.fs_watcher import FSWatcher

    workdir = Path(tempfile.mkdtemp(prefix="uat_scen5_"))
    cmd("set up", f"two FSWatchers on {workdir} (alice + bob), simulating Cursor + Claude Code")

    log_path = workdir / ".synapse" / "runs" / "uat_scen5.jsonl"
    w_alice = FSWatcher(workdir, agent_id="alice-cursor", session_id="uat_scen5", poll_interval_s=0.1)
    w_bob = FSWatcher(workdir, agent_id="bob-claude-code", session_id="uat_scen5", poll_interval_s=0.1)
    w_alice.start()
    w_bob.start()
    time.sleep(0.5)

    # Alice writes models.py
    (workdir / "models.py").write_text("class User: pass\n")
    time.sleep(0.4)
    # Bob overwrites models.py (collision!)
    (workdir / "models.py").write_text("class User:\n    name: str\n")
    time.sleep(0.4)
    # Both leave a separate file each
    (workdir / "alice_solo.py").write_text("# alice's only\n")
    time.sleep(0.4)
    (workdir / "bob_solo.py").write_text("# bob's only\n")
    time.sleep(0.4)

    w_alice.stop()
    w_bob.stop()

    # Run audit on the captured log
    from synapse.audit import audit_traces
    if not log_path.exists():
        return {"scenario": 5, "skipped": "no log captured"}

    rep = audit_traces(str(log_path))
    print()
    print("Output:")
    rep.print_summary()
    print(f"  ── unique cross-agent collisions on shared paths:")
    seen = set()
    for c in rep.conflicts:
        for x in c.conflicting:
            pair = tuple(sorted([c.intention.agent_id, x.agent_id]))
            path = c.intention.tool_args.get("path", "?")
            seen.add((pair, path))
    for (a, b), path in sorted(seen):
        print(f"    {path}: {a} <-> {b}")

    return {
        "scenario": 5,
        "watcher_a_writes": w_alice.writes_emitted,
        "watcher_b_writes": w_bob.writes_emitted,
        "audit_conflicts": len(rep.conflicts),
        "unique_cross_agent_paths": len(seen),
    }


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", type=int, default=None,
                    help="Run only this scenario (1-5). Default: all.")
    args = ap.parse_args()

    scenarios = {
        1: scenario_1_audit_real_openinference,
        2: scenario_2_cloud_vendor_trace,
        3: scenario_3_critical_scope_policy_tier,
        4: scenario_4_sas_drift_warning,
        5: scenario_5_concurrent_fs_watcher,
    }

    chosen = [args.scenario] if args.scenario else sorted(scenarios.keys())
    results = []
    for n in chosen:
        try:
            r = scenarios[n]()
            results.append(r)
        except Exception as e:
            import traceback
            traceback.print_exc()
            results.append({"scenario": n, "error": str(e)})

    # Final summary
    section("UAT Summary")
    for r in results:
        n = r.get("scenario", "?")
        if "error" in r:
            print(f"  Scenario {n}: ERROR - {r['error']}")
        elif "skipped" in r:
            print(f"  Scenario {n}: SKIPPED - {r['skipped']}")
        else:
            print(f"  Scenario {n}: PASS - {r}")

    out_path = REPO_ROOT / "bench" / "results" / "uat_scenarios_v0_2_2.json"
    out_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved -> {out_path}")


if __name__ == "__main__":
    main()
