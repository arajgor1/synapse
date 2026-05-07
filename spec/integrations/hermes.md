# Hermes Agent integration

Hermes Agent ([github.com/NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)) is a self-improving Python agent framework by Nous Research. Per `acp_adapter/tools.py`, every action it takes flows through a typed tool dispatch with explicit `ToolKind` (`read`/`edit`/`execute`/`fetch`/`search`/`think`/`other`).

## **This integration is live-verified.**

Run the Modal smoke (`modal run runtime/modal/framework_sandbox.py::smoke`) and you'll see:

```
[hermes] hook status: {'hooks_installed': ['explicit_wrapper:wrap_tool_call_for_synapse'], 'session_id': 'hermes_smoke'}
[hermes] tool result: wrote 128 bytes to /tmp/synapse_demo.txt
[hermes] envelopes on session stream: 2
  INTENTION     agent=hermes_main scope=['repo.fs.tmp/synapse_demo.txt:w']
  RESOLUTION    agent=hermes_main outcome=success
[hermes] agents registered: 1 (hermes_main, status=active)
[hermes] intentions in state graph: 1 (id=01KR1JKM..., status=resolved)
```

That's real Hermes Agent v0.12.0 installed in a clean Linux container, plus real Redis + Postgres + the Synapse Python SDK + this integration. The protocol envelopes are persisted on both transports.

## TL;DR for Hermes users

```python
import asyncio
from synapse.bus import Bus
from synapse.state import StateGraph
from synapse.integrations.hermes_integration import (
    install_hermes_synapse_hooks,
    wrap_tool_call_for_synapse,
)

async def main():
    bus = Bus(); state = StateGraph("postgresql://...")
    await bus.connect(); await state.connect()

    await install_hermes_synapse_hooks(
        bus=bus, state=state,
        session_id="my_hermes_session",
        agent_id="hermes_main",
        gate_ms=50,
    )

    # Inside Hermes' tool execution path, wrap each tool call:
    async def actual_write(path, content):
        # Hermes' real implementation — write the file
        ...

    result = await wrap_tool_call_for_synapse(
        "write_file",
        {"path": "/tmp/foo.txt", "content": "hello"},
        lambda: actual_write("/tmp/foo.txt", "hello"),
    )

asyncio.run(main())
```

## Tool-classification convention

The integration distinguishes **write/execute tools** (need INTENTION) from **read tools** (pass-through, no overhead):

| Category | Tools | Behavior |
|---|---|---|
| **Write/execute** | `write_file`, `patch`, `terminal`, `process`, `execute_code`, `delegate_task`, `browser_click`, `browser_type`, `browser_navigate`, `image_generate`, `text_to_speech`, `skill_manage`, … | INTENTION + gate + RESOLUTION |
| **Read-only** | `read_file`, `search_files`, `web_search`, `web_extract`, `skill_view`, `skills_list`, `browser_snapshot`, `browser_vision`, `browser_get_images`, `vision_analyze`, … | Pass-through, no INTENTION |
| **Subagent spawn** | `delegate_task` | Same as write + register the delegate as a sub-agent in the same Synapse session |

## Scope mapping

`_scope_from_tool_call(tool_name, args)` maps a Hermes tool call to a Synapse scope:

```
write_file({path: "src/auth.py"})        -> repo.fs.src/auth.py:w
patch({path: "src/main.py"})             -> repo.fs.src/main.py:w
terminal({cmd: "rm -rf /tmp"})           -> repo.shell:w
browser_navigate({url: "https://x.com"}) -> repo.browser.https__x.com:w
delegate_task({agent_id: "child_a"})     -> hermes.subagent.child_a:w
custom_thing({})                         -> hermes.tool.custom_thing:w
```

Path special chars are sanitized so scopes stay parseable.

## Configuration

```python
await install_hermes_synapse_hooks(
    bus=Bus,                  # Required — connected
    state=StateGraph,         # Required — connected
    session_id=str,           # Required
    agent_id="hermes_main",   # Default
    gate_ms=50,               # Default — pre-execution wait window
    fail_on_conflict=False,   # Default — log + continue on CONFLICT.
                              # Set True to raise HermesSynapseConflict so Hermes' existing
                              # tool-error retry loop handles the pivot.
)
```

## Subagent coordination

Hermes' `delegate_task` tool spawns a subagent for parallel work — exactly the scenario Synapse is designed for. When wrapped:

1. Parent agent emits INTENTION on `hermes.subagent.<id>:w`
2. If another delegate already exists on the same `<id>`, the L2 router emits CONFLICT to the parent
3. Otherwise the delegate proceeds and is registered under the same Synapse session, so its own tool calls are also coordinated

This means cross-subagent collisions are caught even when subagents work in parallel.

## Verification

`sdk-python/tests/test_hermes_integration.py` — 15 tests:
- Scope-mapping logic (7 tests)
- `wrap_tool_call_for_synapse` semantics (5 tests: no-op, read-only skip, write emits, failure path, conflict-raise)
- Tool classification sets (3 tests)

15/15 passing in pytest.

Plus the live Modal sandbox smoke documented above.

## Versioning

Hermes Agent is mature and changes shape across versions; this integration is intentionally a **runtime hook**, not a fork or patch of Hermes source. It works against Hermes 0.12.x and is forward-compatible with subsequent versions as long as the tool-name conventions hold.
