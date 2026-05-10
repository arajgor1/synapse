"""Smoke test for the examples/crewai-marketing demo.

Pinning this to CI keeps the README's 60-second walkthrough honest.
If anyone breaks the zero-infra path, the in-process router, or the
ContextVar attribution, this test fails before users ever notice.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_DIR = REPO_ROOT / "examples" / "crewai-marketing"


def _has_demo() -> bool:
    return (DEMO_DIR / "crew.py").exists() and (DEMO_DIR / "crew_no_synapse.py").exists()


@pytest.mark.skipif(not _has_demo(), reason="demo dir missing")
def test_no_synapse_control_loses_one_writer(tmp_path, monkeypatch):
    """Without Synapse, the asyncio.gather'd Writer + Editor produce a
    final post.md that contains EXACTLY ONE of the two contributions —
    the silent-overwrite bug we use to sell coordination."""
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    drafts = DEMO_DIR / "drafts"
    if drafts.exists():
        shutil.rmtree(drafts)

    result = subprocess.run(
        [sys.executable, "crew_no_synapse.py"],
        cwd=str(DEMO_DIR),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, (
        f"crew_no_synapse.py crashed: {result.stderr[:500]}"
    )
    final = (drafts / "post.md").read_text(encoding="utf-8")
    has_writer = "by Writer" in final
    has_editor = "by Editor" in final
    # Exactly one contribution should survive — that's the bug.
    assert has_writer ^ has_editor, (
        f"Expected exactly one writer to win in the no-Synapse control, "
        f"but got writer={has_writer} editor={has_editor}. "
        f"Demo timing may be too forgiving — bump asyncio.sleep values."
    )


@pytest.mark.skipif(not _has_demo(), reason="demo dir missing")
def test_synapse_demo_preserves_both_writers(tmp_path, monkeypatch):
    """With Synapse, the in-process router catches the collision, the
    Editor pivots to post.editor.md, and BOTH writers' work is
    preserved on disk.

    We point SYNAPSE_SQLITE_PATH at a tmp file so prior runs' resolved
    intentions don't surface as 'stale_base_overwrite' conflicts on
    this run (the realistic UX issue any user would hit if they ran the
    demo twice without clearing ~/.synapse/state.db).
    """
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    monkeypatch.delenv("SYNAPSE_OFFLINE", raising=False)
    drafts = DEMO_DIR / "drafts"
    if drafts.exists():
        shutil.rmtree(drafts)

    env = {
        **dict((k, v) for k, v in __import__("os").environ.items()),
        "SYNAPSE_SQLITE_PATH": str(tmp_path / "demo_state.db"),
    }

    result = subprocess.run(
        [sys.executable, "crew.py"],
        cwd=str(DEMO_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, (
        f"crew.py crashed: {result.stderr[:500]}"
    )

    files = {p.name for p in drafts.iterdir()}
    assert "notes.md" in files, "Researcher's notes never landed"

    # Acceptable outcomes:
    #   (a) Writer kept post.md, Editor pivoted -> post.editor.md.
    #   (b) Editor kept post.md, Writer pivoted -> post.writer.md.
    #   (c) Both pivoted (very fast simultaneous arrival) -> both side files.
    # In ALL cases, BOTH agents' work must be preserved on disk somewhere.
    has_writer_text = any(
        "by Writer" in (drafts / f).read_text(encoding="utf-8")
        for f in files if f.endswith(".md")
    )
    has_editor_text = any(
        "by Editor" in (drafts / f).read_text(encoding="utf-8")
        for f in files if f.endswith(".md")
    )
    assert has_writer_text and has_editor_text, (
        f"Synapse failed to preserve both writers — files={files}. "
        f"Writer text present: {has_writer_text}, Editor text present: {has_editor_text}"
    )

    combined = result.stdout + result.stderr
    assert (
        "CONFLICT" in combined
        or "synapse.router" in combined
        or "pivoting to" in combined
    ), (
        "No conflict signal in demo output — router may not have spawned. "
        f"Got stdout: {result.stdout[:300]}\nstderr: {result.stderr[:300]}"
    )
