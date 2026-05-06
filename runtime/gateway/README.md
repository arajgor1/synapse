# Synapse Observability Gateway

FastAPI service that bridges the Redis-backed Synapse bus to browser clients (the Next.js UI in `ui/`).

## Run

```bash
pip install -e sdk-python
pip install fastapi "uvicorn[standard]"
uvicorn runtime.gateway.server:app --port 8000 --reload
```

## Endpoints

### REST

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness check |
| GET | `/sessions` | List sessions with any registered agents (last 50) |
| GET | `/sessions/{id}/agents` | Agents in a session, with capabilities + scopes |
| GET | `/sessions/{id}/intentions?status=active` | Intentions, optionally filtered by status |
| GET | `/sessions/{id}/beliefs` | All beliefs in a session |
| GET | `/sessions/{id}/events?limit=100` | Replay the most recent N envelopes from the session stream |

### WebSocket

`GET /ws/sessions/{session_id}` — upgrades to a WebSocket. Server pushes:

- One `{"type": "snapshot", ...}` message immediately on connect (agents + intentions + beliefs + last 50 events)
- One `{"type": "event", "entry_id": "...", "envelope": {...}}` per new bus message after that

The client can send `"ping"` strings; the server replies `"pong"` for keepalive.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `SYNAPSE_REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `SYNAPSE_POSTGRES_DSN` | `postgresql://synapse:synapse_dev@localhost:5432/synapse` | Postgres connection |

## Implementation notes

- The gateway is stateless. State lives in Redis (the bus) and Postgres (the state graph).
- One background task per session subscribed to the WebSocket. The task self-terminates after the last subscriber disconnects, so memory is bounded.
- CORS is wide-open in dev (`*`); restrict in production.
