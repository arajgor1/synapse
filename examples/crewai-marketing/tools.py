"""Shared tools used by the marketing crew.

Both the Synapse-instrumented crew and the no-Synapse control use the
same tools — Synapse adds coordination at the dispatch layer without
asking the user to change their tool implementations.
"""
from __future__ import annotations

import os
from pathlib import Path

DRAFTS_DIR = Path(__file__).parent / "drafts"


def write_draft(filename: str, content: str) -> str:
    """Write `content` to drafts/<filename>. Returns a short status line."""
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    path = DRAFTS_DIR / filename
    path.write_text(content, encoding="utf-8")
    return f"wrote {path.relative_to(DRAFTS_DIR.parent)} ({len(content)} bytes)"


def read_draft(filename: str) -> str:
    """Read drafts/<filename>. Returns '<empty>' if the file doesn't exist."""
    path = DRAFTS_DIR / filename
    if not path.exists():
        return "<empty>"
    return path.read_text(encoding="utf-8")


def append_to_draft(filename: str, suffix: str) -> str:
    """Read-modify-write — the canonical pattern that loses data under
    concurrent writers. Used by both Writer and Editor in the demo."""
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    path = DRAFTS_DIR / filename
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    new = existing + ("\n" if existing and not existing.endswith("\n") else "") + suffix
    path.write_text(new, encoding="utf-8")
    return f"appended {len(suffix)} bytes to {path.relative_to(DRAFTS_DIR.parent)}"
