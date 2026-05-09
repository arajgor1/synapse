# Streaming dashboard

```bash
python -m synapse.streaming.server --port 8765 --watch .synapse/runs/team.jsonl
```

Stdlib-only WebSocket server. Tails a JSONL audit log; pushes new CONFLICT events to all connected clients with <100ms latency.

Connect from any WS client:

```javascript
const ws = new WebSocket('ws://localhost:8765/');
ws.onmessage = (e) => console.log(JSON.parse(e.data));
```

The Team Health dashboard at `launch/hosted-audit/team-health.html` pulls from this stream.
