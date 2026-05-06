# Synapse Observability UI

Live web dashboard for Synapse multi-agent sessions. Shows agents, intentions, conflicts, beliefs, and an event stream in real-time.

Stack: **Next.js 15** (App Router) · **React 19** · **Tailwind** · **TypeScript**.
Talks to the **gateway service** (FastAPI WebSocket) at `runtime/gateway/server.py`.

## Run it

You need three things up: Redis + Postgres, the gateway, and the Next.js dev server.

```bash
# 1. Bring up infrastructure (from repo root)
docker compose up -d

# 2. Install gateway deps + start gateway (port 8000)
pip install -e sdk-python
pip install fastapi "uvicorn[standard]"
uvicorn runtime.gateway.server:app --port 8000 --reload

# 3. Start the UI dev server (port 3000)
cd ui
npm install
npm run dev
```

Open http://localhost:3000. You'll see a list of sessions (empty if none have run). To populate it, in another shell:

```bash
python examples/two_agents_conflict_demo.py
# or:
python examples/coordinator_demo.py
# or:
python examples/multi_backend_demo.py
```

The session appears in the UI within a couple seconds; click in to watch agents, intentions, conflicts, and the live event stream.

## Layout

- `/` — sessions list (auto-refreshes every 3s)
- `/sessions/[id]` — full session view: agents grid, beliefs panel, intentions table, live event stream

## Architecture

```
Browser (Next.js, :3000)
   │  WebSocket
   ▼
Gateway (FastAPI, :8000)
   │  Redis Streams + Postgres queries
   ▼
Synapse Core (Redis :6379, Postgres :5432)
   ▲
Agents (your Python code using sdk-python)
```

The gateway:
- On WebSocket connect, sends a snapshot (current agents, intentions, beliefs, last 50 events)
- Tails the session's Redis Stream and broadcasts each new envelope to all connected clients
- Exposes REST endpoints for non-realtime queries (`/sessions`, `/sessions/{id}/agents`, etc.)

The UI:
- Maintains client-side state via a reducer keyed off message type
- Filterable event stream (toggle which message types appear)
- Color-coded conflict highlighting on intentions
- Belief divergence detection client-side (red highlight when two agents disagree)

## Production deploy notes (later)

- The gateway is stateless — multiple replicas behind a load balancer is fine.
- The Next.js app produces a `standalone` build (`npm run build`); deploy via Vercel, Cloud Run, or similar.
- Set `NEXT_PUBLIC_GATEWAY_URL` to point the UI at the deployed gateway.
- For multi-tenant deploys, add tenant scoping to the gateway routes (the protocol already supports `tenant_id` in the envelope).
