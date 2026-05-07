"""Importers for normalizing trace exports into AuditEvents.

Each importer accepts a path or stream and yields AuditEvent records.
The pipeline picks the right importer based on file extension or
content sniffing.
"""
from __future__ import annotations

from .jsonl import import_jsonl
from .openinference import import_openinference
from .langsmith import import_langsmith

__all__ = ["import_jsonl", "import_openinference", "import_langsmith", "auto_import"]


def auto_import(path: str):
    """Detect the trace format from the path and dispatch."""
    p = str(path).lower()
    if p.endswith(".jsonl") or p.endswith(".ndjson"):
        return import_jsonl(path)
    if p.endswith(".json"):
        # Could be OpenInference OTel JSON export OR LangSmith export.
        # Sniff the first record.
        return _sniff_and_import(path)
    raise ValueError(
        f"Unknown trace format for {path}. "
        f"Expected .jsonl, .ndjson, or .json. "
        f"Use a specific importer (import_openinference / import_langsmith) "
        f"if your data uses a different extension."
    )


def _sniff_and_import(path: str):
    import json
    from pathlib import Path

    text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text)

    # Heuristic: OpenInference exports are usually a list of spans with
    # `attributes` containing keys like `openinference.span.kind` or
    # `tool.name`. LangSmith exports have a list of run records with
    # `run_type`, `inputs`, `outputs` fields.
    sample = data[0] if isinstance(data, list) and data else data

    if isinstance(sample, dict):
        attrs = sample.get("attributes") or {}
        if any(k.startswith("openinference.") or k.startswith("tool.") for k in attrs):
            return import_openinference(path)
        if "run_type" in sample or "trace_id" in sample and "extra" in sample:
            return import_langsmith(path)
        # OpenInference often wraps spans in {"resourceSpans": [...]}
        if "resourceSpans" in sample or "spans" in sample:
            return import_openinference(path)
        if "runs" in sample or (isinstance(sample, dict) and "session" in sample):
            return import_langsmith(path)

    # Default: try OpenInference first (more common), then LangSmith
    try:
        return import_openinference(path)
    except Exception:
        return import_langsmith(path)
