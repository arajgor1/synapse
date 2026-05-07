"""synapse.audit — read-only conflict detection on existing trace exports.

Consumes traces from any agent framework (via OpenInference OTel,
LangSmith, or generic JSONL), normalizes to AuditEvents, infers scopes
from tool args using rules + optional LLM fallback, and runs the same
L2-style conflict detection used by the live runtime.

Public API:

    from synapse.audit import audit_traces

    report = audit_traces("./langsmith-export.json")
    print(f"Found {report.total_conflicts} silent conflicts")
    report.write_html("./audit.html")
"""
from __future__ import annotations

from .events import AuditEvent
from .pipeline import audit_traces, AuditReport
from .scope_inference import infer_scope, register_scope_rule

__all__ = [
    "AuditEvent",
    "AuditReport",
    "audit_traces",
    "infer_scope",
    "register_scope_rule",
]
