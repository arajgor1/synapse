# Synapse Python SDK

> Phase 1 has shipped. End-to-end coordination flow works against the mock backend; Anthropic adapter is Phase 2.

## Install

```bash
pip install -e .             # from this directory
# or, from the repo root:
pip install -e sdk-python
```

## Phase 1 surface

```python
import asyncio
from synapse import Agent
from synapse.adapters import MockAdapter
from synapse.bus import Bus
from synapse.state import StateGraph

async def main():
    bus = Bus("redis://localhost:6379/0")
    state = StateGraph("postgresql://synapse:synapse_dev@localhost:5432/synapse")
    await bus.connect()
    await state.connect()

    agent = Agent(
        id="agent_a",
        session="my_session",
        backend=MockAdapter(),
        subscribes=["auth.*"],
        scopes_owned=["auth.middleware"],
        bus=bus,
        state=state,
    )

    async with agent.lifecycle():
        intention_id, conflicts = await agent.emit_intention(
            action={"tool": "edit_file", "args": {"path": "auth/middleware.py"}},
            scope=["auth.middleware:w"],
            expected_outcome="Refactor middleware",
            blocking=True,            # wait at gate for CONFLICT signals
            gate_ms=50,               # default per spec
        )

        if conflicts:
            print("Pivot needed:", conflicts[0].suggested_resolution)
        else:
            # Do the work, then resolve
            await agent.emit_resolution(intention_id=intention_id)

asyncio.run(main())
```

## What ships in v0.1.0a0

| Module | Status |
|---|---|
| `synapse.messages` | All 8 message types as Pydantic models, `Envelope.make()` factory |
| `synapse.bus` | Redis Streams client (publish, consumer group, inbox drain) |
| `synapse.state` | Postgres state graph (agents, intentions, scope-overlap query) |
| `synapse.state` (scope matcher) | Wildcard + read/write modifier semantics, fully unit-tested |
| `synapse.agent.Agent` | `lifecycle()`, `emit_intention()`, `emit_resolution()`, `drain_signals()` |
| `synapse.adapters.MockAdapter` | Scripted-response streaming + inject-and-continue |
| `synapse.adapters.base` | `InferenceAdapter` Protocol + `StreamHandle`, `Token` |

## What lands later

| Phase | Adds |
|---|---|
| 2 | `adapters.hosted.Anthropic` with cached-restart injection; `@agent.intention` decorator |
| 3 | `adapters.native.vLLM`, `adapters.local.Ollama` |
| 4 | Coordinator integration (cost telemetry, BLOCK handling) |
| 5 | OpenAI + Gemini adapters; L3 semantic router; PIVOT support in SDK |

## Tests

```bash
pip install pytest pytest-asyncio
pytest tests/
```

39 tests, no infrastructure required (mock-only).

## Module layout

```
synapse/
├── __init__.py
├── agent.py              Agent class + lifecycle
├── messages.py           Pydantic models for all 8 message types
├── bus.py                Redis Streams client
├── state.py              Postgres state graph + scope matcher
└── adapters/
    ├── base.py           InferenceAdapter Protocol
    └── mock.py           Mock adapter (Phase 1)
```

Real adapters land under `adapters/{native,local,hosted}/` in their respective phases.
