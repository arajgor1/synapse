# Synapse framework integrations

Concrete adapters that let popular agent frameworks participate in Synapse coordination without changing their core code.

| Framework | Integration | Status | Doc |
|---|---|---|---|
| **Paperclip AI** | `wrapAdapterWithSynapse(innerAdapter, opts)` (TS) | Adapter shipped; live mock-bus tests pass | [paperclip.md](paperclip.md) |
| **Hermes Agent** | `wrap_tool_call_for_synapse(tool, args, inner)` (Python) | **Live verified** in Modal sandbox: real Hermes + Synapse + Redis + Postgres; INTENTION/RESOLUTION envelopes land on the bus + state graph | [hermes.md](hermes.md) |
| **OpenClaw** | `wrapExtensionWithSynapse(extension, opts)` (TS) | Adapter shipped; inline smoke verified the wrap pattern | [openclaw.md](openclaw.md) |

All three follow the same conceptual integration: **wrap the framework's tool/task dispatch site, emit INTENTION before the action, listen for CONFLICT during the gate window, emit RESOLUTION after the action completes**. The frameworks themselves are unchanged — Synapse adapts to *their* APIs.

## Live verification artifacts

In the Modal sandbox smoke (`bench/results/framework_smoke_*.json`):

```
HERMES integration: real bus + Synapse hook
[hermes] hook status: {'hooks_installed': ['explicit_wrapper:wrap_tool_call_for_synapse'], 'session_id': 'hermes_smoke'}
[hermes] tool result: wrote 128 bytes to /tmp/synapse_demo.txt
[hermes] envelopes on session stream: 2
  INTENTION     agent=hermes_main scope=['repo.fs.tmp/synapse_demo.txt:w']
  RESOLUTION    agent=hermes_main outcome=success
[hermes] agents registered: 1
[hermes] intentions in state graph: 1 (status=resolved)
```

This is real Hermes Agent (NousResearch, v0.12.0) installed via `pip install -e .` in a clean Linux container, with a real Redis bus and real Postgres state graph, exercising the Synapse integration adapter. The protocol envelopes are observable on both transports.
