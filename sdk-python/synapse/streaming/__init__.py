"""synapse.streaming — real-time conflict streaming for live dashboards.

Lets a dashboard (e.g., Synapse Explorer in a browser, a team-health
panel, or another agent) subscribe to CONFLICT and BELIEF DIVERGENCE
events as they happen.

Architecture:
    - tail an audit log (JSONL) OR consume from the live Synapse bus
    - re-evaluate the rolling window on each new event
    - push new conflicts/divergences to subscribers via WebSocket
    - subscribers see <100 ms latency from event-arrival to UI

Run:
    python -m synapse.streaming.server  # opens ws://localhost:8765/

Subscribe (browser):
    const ws = new WebSocket('ws://localhost:8765/');
    ws.onmessage = (e) => render(JSON.parse(e.data));
"""
from .server import main

__all__ = ["main"]
