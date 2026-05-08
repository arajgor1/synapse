"""Importers for normalizing trace exports into AuditEvents.

Each importer accepts a path or stream and yields AuditEvent records.
The pipeline picks the right importer based on file extension or
content sniffing.
"""
from __future__ import annotations

from .jsonl import import_jsonl
from .openinference import import_openinference
from .langsmith import import_langsmith
from .bedrock import import_bedrock
from .vertex import import_vertex
from .azure import import_azure

__all__ = [
    "import_jsonl",
    "import_openinference",
    "import_langsmith",
    "import_bedrock",
    "import_vertex",
    "import_azure",
    "auto_import",
]


def auto_import(path: str):
    """Detect the trace format from the path and dispatch."""
    p = str(path).lower()
    if p.endswith(".jsonl") or p.endswith(".ndjson"):
        return import_jsonl(path)
    if p.endswith(".json"):
        return _sniff_and_import(path)
    raise ValueError(
        f"Unknown trace format for {path}. "
        f"Expected .jsonl, .ndjson, or .json. "
        f"Use a specific importer (import_openinference / import_langsmith / "
        f"import_bedrock / import_vertex / import_azure) "
        f"if your data uses a different extension."
    )


def _sniff_and_import(path: str):
    import json
    from pathlib import Path

    text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text)

    sample = data[0] if isinstance(data, list) and data else data

    if isinstance(sample, dict):
        # Bedrock — has agentSessionId or trace.orchestrationTrace
        if "agentSessionId" in sample or "agentId" in sample:
            return import_bedrock(path)
        if isinstance(sample.get("trace"), dict) and (
            "orchestrationTrace" in sample["trace"]
            or "preProcessingTrace" in sample["trace"]
        ):
            return import_bedrock(path)
        if "traces" in sample and isinstance(sample.get("traces"), list):
            for t in sample["traces"][:1]:
                if isinstance(t, dict) and "orchestrationTrace" in t:
                    return import_bedrock(path)

        # Azure App Insights — has customDimensions or operation_Id
        if "operation_Id" in sample or "customDimensions" in sample:
            return import_azure(path)
        if "value" in sample and isinstance(sample["value"], list) and sample["value"]:
            v0 = sample["value"][0]
            if isinstance(v0, dict) and (
                "operation_Id" in v0 or "customDimensions" in v0
            ):
                return import_azure(path)

        # Vertex — Cloud Trace span shape with gen_ai.* attributes or
        # gcp.vertex.* attributes
        attrs = sample.get("attributes") or {}
        attr_keys = list(attrs.keys()) if isinstance(attrs, dict) else []
        if any(k.startswith("gcp.vertex.") or k.startswith("gen_ai.") for k in attr_keys):
            return import_vertex(path)
        if "spans" in sample and isinstance(sample.get("spans"), list) and sample["spans"]:
            s0 = sample["spans"][0]
            if isinstance(s0, dict):
                a0 = s0.get("attributes") or {}
                a0_keys = list(a0.keys()) if isinstance(a0, dict) else []
                if any(k.startswith("gcp.vertex.") or k.startswith("gen_ai.") for k in a0_keys):
                    return import_vertex(path)

        # OpenInference / OTel
        if any(k.startswith("openinference.") or k.startswith("tool.") for k in attr_keys):
            return import_openinference(path)

        # LangSmith
        if "run_type" in sample or ("trace_id" in sample and "extra" in sample):
            return import_langsmith(path)

        if "resourceSpans" in sample or "spans" in sample:
            return import_openinference(path)
        if "runs" in sample or "session" in sample:
            return import_langsmith(path)

    # Last resort: try OpenInference, then LangSmith
    try:
        return import_openinference(path)
    except Exception:
        return import_langsmith(path)
