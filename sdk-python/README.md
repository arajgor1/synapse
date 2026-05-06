# Synapse Python SDK

> Phase 1 deliverable. Skeleton present; implementation begins after Phase 0 freeze.

## Planned shape

```python
import synapse
from synapse.adapters.hosted import Anthropic

agent = synapse.Agent(
    id="agent_a",
    session="sess_abc",
    backend=Anthropic(model="claude-sonnet-4.6"),
    subscribes=["auth.*"],
    scopes_owned=["auth.middleware"],
)

@agent.intention(scope=["auth.middleware"], blocking=True)
async def refactor_middleware():
    if signal := agent.check_signals():
        await agent.pivot(reason=signal.reason, new_intention=...)
        return

    async with agent.thinking() as thought_stream:
        return await call_llm(thought_stream)
```

## Module layout (planned)

```
synapse/
├── __init__.py
├── agent.py              Agent class, decorators
├── envelope.py           ULID + envelope construction
├── bus.py                Redis Streams client
├── adapters/
│   ├── base.py           InferenceAdapter Protocol
│   ├── hosted/
│   │   ├── anthropic.py  Phase 1
│   │   ├── openai.py     Phase 5
│   │   └── gemini.py     Phase 5
│   ├── local/
│   │   ├── ollama.py     Phase 3
│   │   └── lm_studio.py  Phase 5
│   └── native/
│       ├── vllm.py       Phase 3
│       ├── sglang.py     Phase 5
│       └── tgi.py         Phase 5
├── messages.py           Pydantic models for all 7 message types
└── runtime/              Imports for in-process testing
```

## Status

Empty stub. Implementation lands in Phase 1.
