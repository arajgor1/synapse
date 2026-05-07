"""OpenAI adapter live smoke test.

Verifies, against the real OpenAI API:
1. Can instantiate with OPENAI_API_KEY env
2. start_stream + read_tokens yields text from chunk.choices[0].delta.content
3. cancel preserves partial output
4. inject_and_continue produces a coherent continuation

Cost: ~$0.0005 (gpt-4o-mini, ~50 in + ~50 out tokens across two calls).

Run after `setx OPENAI_API_KEY ...` in PowerShell.
"""

from __future__ import annotations

import asyncio
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_REPO_ROOT, "sdk-python"))


async def main() -> int:
    from synapse.adapters.hosted import OpenAIAdapter

    print("== OpenAI adapter live smoke test ==")
    adapter = OpenAIAdapter(model="gpt-4o-mini", max_tokens=64)
    print(
        f"  model={adapter.capabilities.model_id} "
        f"midstream_inject={adapter.capabilities.supports_midstream_inject}"
    )

    print("\n[1/3] start_stream + read_tokens")
    handle = await adapter.start_stream(
        messages=[
            {"role": "user", "content": "Reply with exactly: alpha bravo charlie"}
        ],
        params={"max_tokens": 16},
    )
    text = ""
    async for tok in adapter.read_tokens(handle):
        text += tok.text
    print(f"  output: {text!r}")
    assert text.strip(), "expected non-empty output"

    print("\n[2/3] inject_and_continue")
    handle2 = await adapter.start_stream(
        messages=[
            {"role": "user", "content": "Tell me a one-sentence story about a fox."},
        ],
        params={"max_tokens": 60},
    )
    partial_chunks: list[str] = []
    async for tok in adapter.read_tokens(handle2):
        partial_chunks.append(tok.text)
        if len(partial_chunks) >= 3:
            break

    new_handle = await adapter.inject_and_continue(
        handle2,
        injection="Make the fox say 'hello' explicitly.",
        instruction="Continue with that.",
    )
    cont = ""
    async for tok in adapter.read_tokens(new_handle):
        cont += tok.text
    print(f"  partial: {''.join(partial_chunks).strip()!r}")
    print(f"  continuation: {cont!r}")
    assert cont, "expected continuation tokens"

    print("\n[3/3] cancel preserves partial")
    handle3 = await adapter.start_stream(
        messages=[{"role": "user", "content": "Count from 1 to 20."}],
        params={"max_tokens": 60},
    )
    it = adapter.read_tokens(handle3)
    first = await it.__anext__()
    partial = await adapter.cancel(handle3)
    print(f"  first token: {first.text!r}")
    print(f"  partial captured: {partial!r}")
    assert partial, "expected non-empty partial"

    print("\n[ok] openai adapter live smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
