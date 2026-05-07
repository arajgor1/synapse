"""Tests for the synapse.audit module.

Each fixture has a known number of planted conflicts; the audit must
catch exactly those, no more no fewer.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from synapse.audit import audit_traces
from synapse.audit.events import AuditEvent, is_write
from synapse.audit.scope_inference import infer_scope, register_scope_rule
from synapse.audit.importers import import_jsonl, import_openinference, import_langsmith


FIXTURES = Path(__file__).parent / "fixtures" / "audit"


# ---------------------------------------------------------------------------
# Importer-level tests
# ---------------------------------------------------------------------------

def test_jsonl_importer_loads_all_records():
    events = list(import_jsonl(FIXTURES / "langgraph_helloworld.jsonl"))
    assert len(events) == 5
    assert events[0].agent_id == "researcher"
    assert events[0].tool_name == "web_search"
    assert events[0].session_id == "lg_demo_1"


def test_openinference_importer_filters_to_tool_spans():
    events = list(import_openinference(FIXTURES / "openinference_otel.json"))
    assert len(events) == 3  # 2 write_file + 1 web_search
    names = {e.tool_name for e in events}
    assert names == {"write_file", "web_search"}
    cart = [e for e in events if e.agent_id == "cart_engineer"][0]
    assert cart.tool_args == {"path": "src/cart_service.py"}


def test_langsmith_importer_only_yields_tool_runs():
    events = list(import_langsmith(FIXTURES / "langsmith_export.json"))
    # 5 records but only 3 are run_type=tool
    assert len(events) == 3
    names = {e.tool_name for e in events}
    assert names == {"write_file", "read_file"}
    assert all(e.session_id == "site_v1" for e in events)


def test_langsmith_importer_propagates_agent_from_parent_chain():
    events = list(import_langsmith(FIXTURES / "langsmith_export.json"))
    designer_writes = [e for e in events if e.agent_id == "designer"]
    frontend_writes = [e for e in events if e.agent_id == "frontend_dev"]
    assert len(designer_writes) >= 1
    assert len(frontend_writes) >= 1


# ---------------------------------------------------------------------------
# Scope inference tests
# ---------------------------------------------------------------------------

def _ev(tool, args=None, agent="a", sess="s"):
    return AuditEvent(
        trace_id="t", span_id="s1", agent_id=agent, session_id=sess,
        tool_name=tool, tool_args=args or {},
        ts_start_ms=0, ts_end_ms=0,
    )


def test_scope_inference_filesystem():
    assert infer_scope(_ev("write_file", {"path": "models/user.py"})) == [
        "repo.fs.models/user.py:w"
    ]
    assert infer_scope(_ev("edit_file", {"file_path": "/etc/config.yaml"})) == [
        "repo.fs.etc/config.yaml:w"
    ]


def test_scope_inference_shell():
    assert infer_scope(_ev("terminal", {"cmd": "ls"})) == ["repo.shell:w"]
    assert infer_scope(_ev("execute_code", {"code": "print(1)"})) == ["repo.shell:w"]


def test_scope_inference_http_writes():
    assert infer_scope(
        _ev("http_request", {"method": "POST", "url": "https://api.x.com/v1/orders"})
    ) == ["http.api.x.com.post:w"]


def test_scope_inference_db():
    assert infer_scope(
        _ev("sql_execute", {"query": "INSERT INTO users (id) VALUES (1)"})
    ) == ["db.users:w"]


def test_scope_inference_browser():
    scope = infer_scope(_ev("browser_click", {"selector": "#submit"}))
    assert scope and scope[0].startswith("repo.browser.")


def test_scope_inference_unknown_tool_returns_empty():
    assert infer_scope(_ev("ponder", {"thought": "hmm"})) == []


def test_register_custom_scope_rule_runs_first():
    seen = {"called": False}

    def custom(ev):
        seen["called"] = True
        if ev.tool_name == "magical_tool":
            return ["my.custom.scope:w"]
        return None

    register_scope_rule(custom)
    assert infer_scope(_ev("magical_tool")) == ["my.custom.scope:w"]
    assert seen["called"] is True


def test_is_write_classifies_writes_correctly():
    assert is_write(_ev("write_file", {"path": "x"}))
    assert is_write(_ev("update_record"))
    assert is_write(_ev("execute_code"))
    assert not is_write(_ev("web_search", {"query": "x"}))
    assert not is_write(_ev("read_file", {"path": "x"}))


# ---------------------------------------------------------------------------
# End-to-end conflict-detection tests
# ---------------------------------------------------------------------------

def test_audit_langgraph_helloworld_finds_2_conflicts():
    """The fixture plants:
      - writer overwriting researcher's notes/research.md (stale_base, +7s gap)
      - reviewer overwriting writer's notes/research.md (stale_base, +9s gap)
    """
    report = audit_traces(FIXTURES / "langgraph_helloworld.jsonl")
    assert report.total_events == 5
    assert report.total_write_events == 4  # 1 search excluded
    assert report.total_conflicts == 2
    assert report.conflict_kinds.get("stale_base_overwrite") == 2
    # Both conflicts target notes/research.md
    for c in report.conflicts:
        assert c.intention.tool_args["path"] == "notes/research.md"


def test_audit_openai_tool_calls_finds_2_conflicts():
    """The fixture plants the Instagram-clone collision pattern:
      - api_engineer overwrites db_engineer's models/user.py  (+7s gap)
      - auth_engineer overwrites both db's and api's models/user.py
    """
    report = audit_traces(FIXTURES / "openai_tool_calls.jsonl")
    assert report.total_events == 5
    assert report.total_conflicts == 2  # 2 overwriting events
    assert all(c.kind == "stale_base_overwrite" for c in report.conflicts)
    # Should attribute waste to clobbered prior writes' tokens
    assert report.estimated_wasted_tokens > 0


def test_audit_openinference_otel_finds_1_conflict():
    """The fixture plants 1 simultaneous active overlap (cart vs payment
    on src/cart_service.py, ts windows overlap)."""
    report = audit_traces(FIXTURES / "openinference_otel.json")
    assert report.total_events == 3
    assert report.total_write_events == 2
    assert report.total_conflicts == 1
    c = report.conflicts[0]
    assert c.intention.agent_id == "payment_engineer"
    assert c.kind == "scope_overlap"  # overlapping time windows
    assert "src/cart_service.py" in c.intention.tool_args.get("path", "")


def test_audit_langsmith_export_finds_1_conflict():
    """The fixture plants:
      - designer wrote design_tokens.json @ 10:00:04
      - frontend wrote design_tokens.json @ 10:00:13 (+9s gap; stale_base)
    Read tool at 10:00:16 is excluded (write_only=True).
    """
    report = audit_traces(FIXTURES / "langsmith_export.json")
    assert report.total_events == 3  # 3 tool runs (2 write + 1 read)
    assert report.total_write_events == 2
    assert report.total_conflicts == 1
    c = report.conflicts[0]
    assert c.intention.agent_id == "frontend_dev"
    assert c.kind == "stale_base_overwrite"


def test_audit_html_report_renders(tmp_path):
    report = audit_traces(FIXTURES / "openai_tool_calls.jsonl")
    out = tmp_path / "audit.html"
    report.write_html(str(out))
    text = out.read_text(encoding="utf-8")
    assert "<title>Synapse Audit" in text
    assert "stale_base_overwrite" in text or "STALE-BASE OVERWRITE" in text
    assert "models/user.py" in text


def test_audit_json_report_serializable(tmp_path):
    report = audit_traces(FIXTURES / "langsmith_export.json")
    out = tmp_path / "audit.json"
    report.write_json(str(out))
    import json
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["total_conflicts"] == 1
    assert "conflicts" in loaded
    assert loaded["conflicts"][0]["kind"] == "stale_base_overwrite"


def test_audit_lookback_window_excludes_old_events():
    """If the resolved-lookback is < gap, no stale_base conflicts fire."""
    report = audit_traces(
        FIXTURES / "langgraph_helloworld.jsonl",
        lookback_ms=1000,  # 1 second — less than the 7s gaps in the fixture
    )
    assert report.total_conflicts == 0


def test_audit_include_reads_does_not_create_phantom_conflicts():
    """Adding read events shouldn't create conflicts (reads can't collide)."""
    r_default = audit_traces(FIXTURES / "openai_tool_calls.jsonl")
    r_with_reads = audit_traces(FIXTURES / "openai_tool_calls.jsonl", write_only=False)
    assert r_default.total_conflicts == r_with_reads.total_conflicts


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------

def test_cli_audit_command(tmp_path):
    from synapse.cli.main import main as cli_main

    out_html = tmp_path / "audit.html"
    out_json = tmp_path / "audit.json"

    rc = cli_main([
        "audit",
        str(FIXTURES / "openai_tool_calls.jsonl"),
        "--html", str(out_html),
        "--json", str(out_json),
        "--no-summary",
    ])
    assert rc == 0
    assert out_html.exists()
    assert out_json.exists()
