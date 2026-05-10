"""The same flow as crew_no_synapse.py, with Synapse coordinating.

Two parallel tasks (Writer + Editor) both want to write ``drafts/post.md``.
Each wraps its tool call in ``synapse.intend(...)`` with the file path
as the scope. When the second writer arrives during the first writer's
gate window, Synapse's auto-spawned in-process router detects the scope
overlap and pushes a CONFLICT envelope back. The second writer's
handle reports ``has_conflicts == True`` and the agent's code pivots
to a fresh filename instead of clobbering.

Run alongside ``synapse watch`` to see live events:

    # Terminal 1
    synapse watch --session crew_demo

    # Terminal 2
    python crew.py
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import time
from pathlib import Path

# Make `tools.py` importable when run as a script.
sys.path.insert(0, str(Path(__file__).parent))

import synapse
from tools import DRAFTS_DIR, append_to_draft, read_draft

POST = "post.md"
# Unique session per run so SQLite state from prior runs doesn't surface
# as "stale_base_overwrite" conflicts. Override via SYNAPSE_SESSION_ID
# when you want a deterministic session name (e.g. for `synapse watch`).
SESSION = os.environ.get("SYNAPSE_SESSION_ID") or f"crew_demo_{int(time.time())}"


async def writer_task() -> str:
    """Writer agent — claims drafts/post.md, drafts the body."""
    with synapse.with_agent("writer"):
        async with synapse.intend(
            scope=[f"repo.fs.drafts/{POST}:w"],
            agent="writer",
            session=SESSION,
            expected_outcome=f"writer drafts {POST}",
            blocking=True,
            gate_ms=300,
        ) as i:
            if i.has_conflicts:
                # The Writer arrived second — pivot to a versioned name.
                target = "post.writer.md"
                print(
                    f"  WRITER: SYNAPSE CONFLICT on {POST} — pivoting to {target}"
                )
            else:
                target = POST
            existing = await asyncio.to_thread(read_draft, target)
            await asyncio.sleep(0.4)  # simulate LLM generation
            text = (
                "## Body (by Writer)\n"
                "Synapse coordinates multi-agent AI systems so they don't "
                "step on each other. This is the body the Writer drafted.\n"
            )
            if existing != "<empty>":
                text = existing + "\n" + text
            result = await asyncio.to_thread(_write_full, target, text)
            i.set_state_diff({"output_preview": result})
            return result


async def editor_task() -> str:
    """Editor agent — claims drafts/post.md, appends a TL;DR."""
    await asyncio.sleep(0.05)  # editor arrives slightly later
    with synapse.with_agent("editor"):
        async with synapse.intend(
            scope=[f"repo.fs.drafts/{POST}:w"],
            agent="editor",
            session=SESSION,
            expected_outcome=f"editor revises {POST}",
            blocking=True,
            gate_ms=300,
        ) as i:
            if i.has_conflicts:
                target = "post.editor.md"
                print(
                    f"  EDITOR: SYNAPSE CONFLICT on {POST} — pivoting to {target}"
                )
            else:
                target = POST
            existing = await asyncio.to_thread(read_draft, target)
            await asyncio.sleep(0.1)
            text = (
                "## TL;DR (by Editor)\n"
                "Multi-agent systems silently collide. Use Synapse.\n"
            )
            if existing != "<empty>":
                text = existing + "\n" + text
            result = await asyncio.to_thread(_write_full, target, text)
            i.set_state_diff({"output_preview": result})
            return result


async def researcher_task() -> str:
    """Researcher: writes a separate notes.md — never collides. Included
    so the dashboard shows multi-agent activity, not just the conflict."""
    with synapse.with_agent("researcher"):
        async with synapse.intend(
            scope=["repo.fs.drafts/notes.md:w"],
            agent="researcher",
            session=SESSION,
            expected_outcome="researcher gathers notes",
            blocking=False,
        ) as i:
            await asyncio.sleep(0.1)
            text = (
                "## Research notes (by Researcher)\n"
                "- Synapse adapter coverage: 11 frameworks\n"
                "- AgenticFlict F1: 0.865\n"
                "- Zero-infra mode: in-memory bus + SQLite\n"
            )
            result = await asyncio.to_thread(_write_full, "notes.md", text)
            i.set_state_diff({"output_preview": result})
            return result


def _write_full(filename: str, content: str) -> str:
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    path = DRAFTS_DIR / filename
    path.write_text(content, encoding="utf-8")
    return f"wrote {path.name} ({len(content)} bytes)"


async def main() -> None:
    if DRAFTS_DIR.exists():
        shutil.rmtree(DRAFTS_DIR)
    DRAFTS_DIR.mkdir(parents=True)

    print("=== running CrewAI-style flow WITH Synapse ===")
    print(f"  session = {SESSION}")
    if not os.environ.get("SYNAPSE_REDIS_URL"):
        print("  mode    = zero-infra (in-memory bus + SQLite, no infra needed)")
    else:
        print("  mode    = live (Redis + Postgres)")
    print()

    researcher, writer, editor = await asyncio.gather(
        researcher_task(), writer_task(), editor_task(),
    )
    print()
    print(f"Researcher: {researcher}")
    print(f"Writer    : {writer}")
    print(f"Editor    : {editor}")

    print("\nFinal drafts/ contents:")
    for f in sorted(DRAFTS_DIR.iterdir()):
        print(f"  - {f.name} ({f.stat().st_size} bytes)")
    print()
    if (DRAFTS_DIR / "post.writer.md").exists() or (DRAFTS_DIR / "post.editor.md").exists():
        print("Synapse caught the collision — second writer pivoted to a fresh filename.")
        print("BOTH agents' work survived. Compare to crew_no_synapse.py.")
    else:
        # Both writers executed serialised through different pivots
        print("Both writers wrote to the canonical name (timing avoided collision).")
        print("Re-run a few times — Synapse will catch it on the races.")


if __name__ == "__main__":
    asyncio.run(main())
