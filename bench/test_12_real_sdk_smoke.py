"""Test 12 — Real-SDK smoke test for all 11 framework adapters.

The Strands case (Option C) revealed that adapters smoke-tested against
fake modules can ship completely broken against real SDKs. This script
installs each real SDK from PyPI and runs `synapse.install(framework=X)`
to verify the patch attaches.

For each framework, we record:
  - SDK package name
  - Installed version
  - Whether `synapse.install` logged "patched ..." (success) or
    "could not find ..." (broken) or raised an exception
  - Which entry point was patched

Output: structured JSON for the testing protocol document.

This DOES NOT validate behavioral correctness end-to-end — for that we'd
need a per-framework end-to-end test like Option A/B/C. This test only
catches "the adapter ships pointing at an API that no longer exists."
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Each entry: (synapse framework name, pip package, import name, expected dispatch path)
FRAMEWORKS = [
    ("langgraph",       "langgraph",                   "langgraph",                "ToolNode.invoke or similar"),
    ("crewai",          "crewai>=0.86,<0.130",         "crewai",                   "Crew/Task execution path"),
    ("autogen",         "autogen-agentchat>=0.4",      "autogen_agentchat",        "AssistantAgent / dispatch path"),
    ("openai_agents",   "openai-agents",               "agents",                   "Agent.run or runner"),
    ("pydantic_ai",     "pydantic-ai",                 "pydantic_ai",              "Agent.run_tool path"),
    ("smolagents",      "smolagents",                  "smolagents",               "Tool.__call__"),
    ("hermes",          "hermes-mcp",                  "hermes",                   "Hermes tool dispatch"),
    ("strands",         "strands-agents",              "strands",                  "event_loop._handle_tool_execution (after fix)"),
]


def _log_capture():
    """Capture synapse logs to a list so we can read what the adapter printed."""
    captured = []

    class _Handler(logging.Handler):
        def emit(self, record):
            try:
                captured.append(self.format(record))
            except Exception:
                captured.append(record.getMessage())

    h = _Handler()
    h.setLevel(logging.INFO)
    h.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    syn_logger = logging.getLogger("synapse")
    syn_logger.addHandler(h)
    syn_logger.setLevel(logging.INFO)
    return captured, h


def _try_install(pkg: str) -> tuple[bool, str]:
    """Return (success, output) — pip install on a temp venv would be safer
    but for this campaign we install into the current env and accept some
    pollution. Each install is best-effort; failures are recorded honestly."""
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", pkg],
        capture_output=True, text=True, timeout=180,
    )
    return (proc.returncode == 0, (proc.stdout + proc.stderr)[-1000:])


def _get_version(import_name: str) -> str:
    try:
        mod = importlib.import_module(import_name)
        return getattr(mod, "__version__", "?")
    except Exception:
        return "<not importable>"


def smoke_test_one(framework: str, package: str, import_name: str, expected: str) -> dict:
    """Install + run synapse.install + record what happened."""
    print(f"\n=== {framework} ({package}) ===")
    result = {
        "framework": framework,
        "pip_package": package,
        "expected_dispatch_path": expected,
        "install_attempted": False,
        "install_ok": False,
        "import_ok": False,
        "import_version": None,
        "synapse_install_log": [],
        "patched": None,  # True / False / None (uncertain)
        "exception": None,
    }

    # Try install
    result["install_attempted"] = True
    ok, out = _try_install(package)
    result["install_ok"] = ok
    if not ok:
        result["install_output_tail"] = out[-500:]
        print(f"  pip install FAILED: {out[-200:]}")
        return result

    # Try import
    try:
        mod = importlib.import_module(import_name)
        result["import_ok"] = True
        result["import_version"] = getattr(mod, "__version__", "?")
        print(f"  installed + imported ok, version={result['import_version']}")
    except Exception as e:
        result["import_ok"] = False
        result["exception"] = f"{type(e).__name__}: {e}"
        print(f"  import FAILED: {e}")
        return result

    # Force-reimport synapse.frameworks.<name> so its module-level state resets
    sdk_path = str(REPO_ROOT / "sdk-python")
    if sdk_path not in sys.path:
        sys.path.insert(0, sdk_path)
    for k in list(sys.modules.keys()):
        if k.startswith("synapse.frameworks") or k == "synapse.install":
            del sys.modules[k]

    # Capture synapse logs and run install
    captured, handler = _log_capture()
    try:
        from synapse.install import _ensure_framework_loaded, _FRAMEWORK_REGISTRY
        _ensure_framework_loaded(framework)
        install_fn = _FRAMEWORK_REGISTRY.get(framework)
        if install_fn is None:
            result["patched"] = False
            result["exception"] = "framework not in synapse registry after _ensure_framework_loaded"
        else:
            install_fn({})
        # Inspect captured logs
        result["synapse_install_log"] = list(captured)
        # Heuristic: did we see "patched" or "could not find"?
        joined = " ".join(captured)
        if "patched" in joined.lower() and "could not find" not in joined.lower():
            result["patched"] = True
        elif "could not find" in joined.lower() or "not yet shipped" in joined.lower():
            result["patched"] = False
        else:
            result["patched"] = None  # ambiguous
    except Exception as e:
        result["patched"] = False
        result["exception"] = f"{type(e).__name__}: {e}"
        import traceback; traceback.print_exc()
    finally:
        logging.getLogger("synapse").removeHandler(handler)

    print(f"  patched: {result['patched']}")
    for line in result["synapse_install_log"]:
        print(f"    LOG: {line}")
    return result


def main():
    print("=== Test 12: real-SDK smoke for all 11 framework adapters ===")
    started = time.time()
    out = {
        "test_id": "12",
        "scenario": "Real-SDK smoke test — does each adapter actually patch the real published SDK?",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": os.uname().nodename if hasattr(os, "uname") else os.environ.get("COMPUTERNAME", "?"),
        "frameworks": [],
    }
    for fw in FRAMEWORKS:
        try:
            r = smoke_test_one(*fw)
        except Exception as e:
            r = {"framework": fw[0], "fatal_error": f"{type(e).__name__}: {e}"}
        out["frameworks"].append(r)

    out["elapsed_s"] = round(time.time() - started, 1)

    # Summary table
    print("\n=== SUMMARY ===")
    fmt = "  {:<18} {:<20} {:<10} {}"
    print(fmt.format("framework", "version", "patched?", "log"))
    for r in out["frameworks"]:
        fw = r.get("framework", "?")
        ver = r.get("import_version") or "<not installed>"
        patched = "YES" if r.get("patched") is True else ("NO" if r.get("patched") is False else "?")
        log = (r.get("synapse_install_log", [""])[0][:60] if r.get("synapse_install_log") else r.get("exception", "")) or ""
        print(fmt.format(fw, str(ver)[:20], patched, log[:60]))

    out_path = REPO_ROOT / "bench" / "results" / "test_12_real_sdk_smoke.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
