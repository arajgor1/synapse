"""Control: the same 3-agent flow WITHOUT Synapse.

Demonstrates the silent-overwrite collision Synapse is designed to
catch. Run this first to see the bug, then run ``crew.py`` to see
Synapse catch it.

Two parallel `asyncio.gather`'d tasks both append to ``drafts/post.md``.
Each does read-modify-write. The second writer reads BEFORE the first
writes, so its append clobbers the first's contribution. No error, no
warning — the first writer's text is just gone.

This is the deterministic version of the timing bug that bites real
CrewAI deployments using ``async_execution=True`` or ``kickoff_for_each``
on overlapping outputs.
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from tools import DRAFTS_DIR, append_to_draft, read_draft

POST = "post.md"


async def writer_task() -> str:
    """Writer: drafts the body of the post."""
    # Simulate the LLM thinking time — Writer reads the file early then
    # commits later, exactly like a real LLM tool-call sequence.
    existing = await asyncio.to_thread(read_draft, POST)
    await asyncio.sleep(0.4)  # "LLM is generating..."
    text = (
        "## Body (by Writer)\n"
        "Synapse coordinates multi-agent AI systems so they don't step "
        "on each other. This is the body the Writer drafted.\n"
    )
    if existing != "<empty>":
        text = existing + "\n" + text
    return await asyncio.to_thread(_write_full, POST, text)


async def editor_task() -> str:
    """Editor: appends a TL;DR. Wakes up SECOND but finishes FIRST
    because its work is shorter."""
    await asyncio.sleep(0.05)  # editor wakes slightly later
    existing = await asyncio.to_thread(read_draft, POST)
    await asyncio.sleep(0.1)
    text = (
        "## TL;DR (by Editor)\n"
        "Multi-agent systems silently collide. Use Synapse.\n"
    )
    if existing != "<empty>":
        text = existing + "\n" + text
    return await asyncio.to_thread(_write_full, POST, text)


def _write_full(filename: str, content: str) -> str:
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    path = DRAFTS_DIR / filename
    path.write_text(content, encoding="utf-8")
    return f"wrote {path.name} ({len(content)} bytes)"


async def main() -> None:
    # Start clean
    if DRAFTS_DIR.exists():
        shutil.rmtree(DRAFTS_DIR)
    DRAFTS_DIR.mkdir(parents=True)

    print("=== running CrewAI-style flow WITHOUT Synapse ===")
    writer_result, editor_result = await asyncio.gather(writer_task(), editor_task())
    print(f"Writer: {writer_result}")
    print(f"Editor: {editor_result}")

    final = (DRAFTS_DIR / POST).read_text(encoding="utf-8")
    print(f"\nFinal contents of {POST}:")
    print("-" * 40)
    print(final)
    print("-" * 40)
    if "by Writer" in final and "by Editor" in final:
        print("BOTH writes survived (timing was lucky).")
    elif "by Writer" in final:
        print("WRITER won — Editor's TL;DR was silently lost.")
    elif "by Editor" in final:
        print("EDITOR won — Writer's body was silently lost.")
    else:
        print("Neither — something went very wrong.")


if __name__ == "__main__":
    asyncio.run(main())
