"""`synapse spec validate` — validate envelopes against v1.0 schemas.

Usage:
  synapse spec validate path/to/envelope.json
  synapse spec validate --jsonl events.ndjson
  cat envelope.json | synapse spec validate
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable


def _spec_dir() -> Path:
    """Find the spec/protocol-v1.0 directory.

    Tries (in order): SYNAPSE_SPEC_DIR env, $CWD/spec, walking up to find one,
    package-relative.
    """
    env = os.environ.get("SYNAPSE_SPEC_DIR")
    if env:
        return Path(env)
    cwd = Path.cwd()
    for c in [cwd, *cwd.parents]:
        cand = c / "spec" / "protocol-v1.0"
        if cand.is_dir():
            return cand
    raise RuntimeError(
        "Cannot locate spec/protocol-v1.0/. Set SYNAPSE_SPEC_DIR or run from a "
        "Synapse repo checkout."
    )


def _load_schemas() -> tuple[dict, dict[str, dict]]:
    """Returns (envelope_schema, payload_schemas_by_type)."""
    spec = _spec_dir()
    envelope = json.loads((spec / "envelope.schema.json").read_text())
    types = {
        "THOUGHT": "thought.schema.json",
        "INTENTION": "intention.schema.json",
        "PIVOT": "pivot.schema.json",
        "BELIEF": "belief.schema.json",
        "BLOCK": "block.schema.json",
        "CONFLICT": "conflict.schema.json",
        "RESOLUTION": "resolution.schema.json",
        "COST_REPORT": "cost_report.schema.json",
    }
    payloads = {
        t: json.loads((spec / fname).read_text()) for t, fname in types.items()
    }
    return envelope, payloads


def _iter_inputs(paths: list[str], json_lines: bool) -> Iterable[tuple[str, Any]]:
    """Yield (label, parsed_json) for each envelope to validate."""
    if not paths:
        text = sys.stdin.read()
        if json_lines:
            for i, line in enumerate(text.splitlines(), 1):
                line = line.strip()
                if not line:
                    continue
                yield f"<stdin>:{i}", json.loads(line)
        else:
            yield "<stdin>", json.loads(text)
        return
    for p in paths:
        path = Path(p)
        text = path.read_text()
        if json_lines:
            for i, line in enumerate(text.splitlines(), 1):
                line = line.strip()
                if not line:
                    continue
                yield f"{path}:{i}", json.loads(line)
        else:
            yield str(path), json.loads(text)


def run_validate(paths: list[str], json_lines: bool) -> int:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        print(
            "jsonschema not installed. `pip install jsonschema>=4.20`.",
            file=sys.stderr,
        )
        return 2

    envelope_schema, payload_schemas = _load_schemas()
    env_validator = Draft202012Validator(envelope_schema)
    payload_validators = {
        t: Draft202012Validator(s) for t, s in payload_schemas.items()
    }

    total = 0
    failed = 0
    for label, doc in _iter_inputs(paths, json_lines):
        total += 1
        env_errors = sorted(env_validator.iter_errors(doc), key=lambda e: e.path)
        if env_errors:
            failed += 1
            print(f"FAIL {label} (envelope):")
            for e in env_errors:
                print(f"  - {'/'.join(map(str, e.path)) or '<root>'}: {e.message}")
            continue

        mtype = doc.get("type")
        pv = payload_validators.get(mtype)
        if pv is None:
            failed += 1
            print(f"FAIL {label}: unknown type {mtype!r}")
            continue
        payload = doc.get("payload", {})
        payload_errors = sorted(pv.iter_errors(payload), key=lambda e: e.path)
        if payload_errors:
            failed += 1
            print(f"FAIL {label} (payload type={mtype}):")
            for e in payload_errors:
                print(f"  - {'/'.join(map(str, e.path)) or '<root>'}: {e.message}")
            continue
        print(f"OK   {label} (type={mtype})")

    print(
        f"\n{total - failed}/{total} valid"
        + (" — all good." if failed == 0 else f", {failed} invalid.")
    )
    return 0 if failed == 0 else 1
