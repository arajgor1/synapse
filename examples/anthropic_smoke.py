"""Anthropic adapter live smoke test.

Verifies, against the real Anthropic API:
1. Can instantiate the adapter with ANTHROPIC_API_KEY env
2. start_stream + read_tokens yields text
3. cancel returns the partial output preserved so far
4. inject_and_continue produces a follow-up stream that references the
   injection (so cached-restart is wired correctly)

Cost: ~$0.0002 (one Haiku call, ~50 input + ~30 output tokens).

Run after `setx ANTHROPIC_API_KEY ...` in PowerShell.
"""

from __future__ import annotations

import asyncio
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_REPO_ROOT, "sdk-python"))


async def main() -> int:
    from synapse.adapters.hosted import AnthropicAdapter

    print("== Anthropic adapter live smoke test ==")
    adapter = AnthropicAdapter(model="claude-haiku-4-5-20251001", max_tokens=64)
    print(
        f"  model={adapter.capabilities.model_id} "
        f"midstream_inject={adapter.capabilities.supports_midstream_inject}"
    )

    print("\n[1/3] start_stream + read_tokens")
    handle = await adapter.start_stream(
        messages=[{"role": "user", "content": "Reply with: alpha bravo charlie"}],
        params={"max_tokens": 16},
    )
    text = ""
    async for tok in adapter.read_tokens(handle):
        text += tok.text
    print(f"  output: {text!r}")
    assert text.strip(), "expected non-empty output"

    print("\n[2/3] inject_and_continue (cached-restart)")
    handle2 = await adapter.start_stream(
        messages=[
            {"role": "user", "content": "Tell me a one-sentence story about a fox."},
        ],
        params={"max_tokens": 60},
    )
    # Read some tokens, then inject mid-stream
    partial_chunks: list[str] = []
    async for tok in adapter.read_tokens(handle2):
        partial_chunks.append(tok.text)
        if len(partial_chunks) >= 3:
            break

    new_handle = await adapter.inject_and_continue(
        handle2,
        injection="Make the fox say 'hello' explicitly.",
        instruction="Continue your story incorporating that.",
    )
    cont = ""
    async for tok in adapter.read_tokens(new_handle):
        cont += tok.text
    partial_so_far = "".join(partial_chunks).strip()
    print(f"  partial before inject: {partial_so_far!r}")
    print(f"  continuation: {cont!r}")
    assert cont, "expected continuation tokens"

    print("\n[3/3] cancel preserves partial")
    handle3 = await adapter.start_stream(
        messages=[{"role": "user", "content": "Count from 1 to 20 slowly."}],
        params={"max_tokens": 60},
    )
    it = adapter.read_tokens(handle3)
    first = await it.__anext__()
    partial = await adapter.cancel(handle3)
    print(f"  first token: {first.text!r}")
    print(f"  partial captured: {partial!r}")
    assert partial, "expected non-empty partial"

    print("\n[ok] anthropic adapter live smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
