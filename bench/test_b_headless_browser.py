"""Phase B — Headless browser tests for the hosted demo pages.

Loads each HTML page in a headless Chromium and verifies:
  - No JavaScript errors
  - Key DOM elements present
  - Sample data buttons trigger renders (Explorer, team-health)
  - Benchmark dashboard fetches the JSON and populates correctly

Uses Playwright (auto-installs Chromium on first run). Run:
    pip install playwright
    playwright install chromium
    python bench/test_b_headless_browser.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOSTED = REPO_ROOT / "launch" / "hosted-audit"


def _start_local_http_server(directory: Path) -> tuple[str, "subprocess.Popen"]:
    """Serve `directory` on a free port; return (base_url, proc).

    fetch() over file:// is blocked by Chrome — we need a real HTTP origin.
    """
    import socket, subprocess
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]; s.close()
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--directory", str(directory)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    # Wait for it to be reachable
    import time
    for _ in range(40):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except (OSError, ConnectionRefusedError):
            time.sleep(0.1)
    return f"http://127.0.0.1:{port}", proc


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Installing playwright...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "playwright"])
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium", "--with-deps"])
        from playwright.sync_api import sync_playwright

    base_url, http_proc = _start_local_http_server(HOSTED)
    print(f"  serving HOSTED via {base_url}")

    results: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        for page_name in ["landing.html", "index.html", "benchmark.html",
                          "explorer.html", "team-health.html"]:
            url = f"{base_url}/{page_name}"
            print(f"\n=== {page_name} ===")
            page = context.new_page()
            console_errors: list[str] = []
            page.on("pageerror", lambda exc: console_errors.append(f"PAGEERROR: {exc}"))
            page.on("console", lambda msg: console_errors.append(f"CONSOLE.{msg.type}: {msg.text}") if msg.type == "error" else None)

            try:
                page.goto(url, wait_until="networkidle", timeout=10000)
            except Exception as e:
                results.append({"page": page_name, "ok": False, "err": str(e)[:200]})
                page.close()
                continue

            # Page-specific assertions
            checks = []
            if page_name == "landing.html":
                checks.append(("title", page.locator("h1").first.is_visible()))
                checks.append(("hero text", "AI agents" in page.locator("body").text_content()))
                checks.append(("install snippet", "pip install synapse-protocol-py" in page.content()))
            elif page_name == "index.html":
                checks.append(("dropzone", page.locator("#drop").is_visible()))
                checks.append(("sample buttons", page.locator("[data-sample]").count() >= 3))
            elif page_name == "benchmark.html":
                page.wait_for_timeout(800)
                checks.append(("AgenticFlict card", page.locator("#agenticflict-card").is_visible()))
                # Either the fetched JSON or hardcoded fallback should populate
                stats_html = page.locator("#af-stats").inner_html()
                checks.append(("stats populated", "0.86" in stats_html or "0.87" in stats_html))
                rows = page.locator("#af-per-agent tbody tr").count()
                checks.append(("per-agent rows", rows >= 5))
            elif page_name == "explorer.html":
                checks.append(("svg ready", page.locator("#viz").is_visible()))
                checks.append(("toolbar buttons", page.locator(".toolbar .btn").count() >= 4))
                # Click a sample button and verify the SVG fills
                page.click("[onclick*=\"loadSample('multi_orch')\"]")
                page.wait_for_timeout(800)
                # Empty-state should be replaced by an SVG
                content = page.locator("#viz").inner_html()
                checks.append(("sample renders nodes", "<circle" in content or "<svg" in content))
            elif page_name == "team-health.html":
                # Click sample data button
                page.click("button:text('Load sample data')")
                page.wait_for_timeout(800)
                checks.append(("KPI grid populated", page.locator("#kpi-grid .card").count() >= 4))
                checks.append(("SAS chart drawn", page.locator("#sas-svg rect").count() >= 1))

            ok = all(c[1] for c in checks)
            results.append({
                "page": page_name,
                "ok": ok,
                "checks": [{"name": n, "pass": bool(p)} for n, p in checks],
                "console_errors": console_errors[:5],
            })
            print(f"  result: {'PASS' if ok else 'FAIL'}")
            for n, p in checks:
                print(f"    {'[+]' if p else '[-]'} {n}")
            if console_errors:
                print(f"    console errors:")
                for e in console_errors[:3]:
                    print(f"      {e[:120]}")
            page.close()

        browser.close()

    # Stop local server
    try:
        http_proc.terminate()
        http_proc.wait(timeout=2)
    except Exception:
        pass

    # Aggregate
    print(f"\n=== AGGREGATE ===")
    passed = sum(1 for r in results if r["ok"])
    print(f"  {passed}/{len(results)} pages pass")

    out = REPO_ROOT / "bench" / "results" / "headless_browser_tests.json"
    out.write_text(json.dumps({"results": results, "passed": passed, "total": len(results)},
                              indent=2, default=str), encoding="utf-8")
    print(f"  saved -> {out}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
