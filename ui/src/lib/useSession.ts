"use client";

import { useEffect, useReducer, useRef } from "react";
import type {
  Agent,
  Belief,
  Envelope,
  EventMessage,
  Intention,
  SnapshotMessage,
  WSMessage,
} from "./types";

// -----------------------------------------------------------------------------
// State + reducer
// -----------------------------------------------------------------------------
export interface SessionState {
  connected: boolean;
  sessionId: string;
  agents: Map<string, Agent>;
  intentions: Map<string, Intention>;
  beliefs: Map<string, Belief[]>; // key -> beliefs across agents
  events: Array<{ entry_id: string; envelope: Envelope }>;
  costUsd: number;
  conflictsByIntention: Map<string, number>; // intention_id -> conflict count
}

type Action =
  | { kind: "snapshot"; msg: SnapshotMessage }
  | { kind: "event"; msg: EventMessage }
  | { kind: "connected"; connected: boolean };

const MAX_EVENTS = 500;

function initial(sessionId: string): SessionState {
  return {
    connected: false,
    sessionId,
    agents: new Map(),
    intentions: new Map(),
    beliefs: new Map(),
    events: [],
    costUsd: 0,
    conflictsByIntention: new Map(),
  };
}

function reduce(state: SessionState, action: Action): SessionState {
  switch (action.kind) {
    case "connected":
      return { ...state, connected: action.connected };
    case "snapshot": {
      const agents = new Map<string, Agent>();
      action.msg.agents.forEach((a) => agents.set(a.id, a));
      const intentions = new Map<string, Intention>();
      action.msg.intentions.forEach((i) => intentions.set(i.id, i));
      const beliefs = new Map<string, Belief[]>();
      action.msg.beliefs.forEach((b) => {
        const arr = beliefs.get(b.key) || [];
        arr.push(b);
        beliefs.set(b.key, arr);
      });
      return {
        ...state,
        agents,
        intentions,
        beliefs,
        events: action.msg.events.slice(-MAX_EVENTS),
        conflictsByIntention: new Map(),
      };
    }
    case "event": {
      const env = action.msg.envelope;
      const events = [...state.events, action.msg].slice(-MAX_EVENTS);
      let intentions = state.intentions;
      let beliefs = state.beliefs;
      const conflicts = new Map(state.conflictsByIntention);
      let costUsd = state.costUsd;

      switch (env.type) {
        case "INTENTION": {
          const p = env.payload as Partial<Intention> & {
            scope: string[];
            action: Intention["action"];
            expected_outcome: string;
          };
          const next = new Map(intentions);
          next.set(env.msg_id, {
            id: env.msg_id,
            agent_id: env.agent_id,
            scope: p.scope,
            action: p.action,
            expected_outcome: p.expected_outcome,
            blocking: !!p.blocking,
            status: "active",
            created_at: new Date(env.timestamp_ms).toISOString(),
            resolved_at: null,
          });
          intentions = next;
          break;
        }
        case "RESOLUTION": {
          const p = env.payload as { intention_id: string; outcome?: string };
          const target = intentions.get(p.intention_id);
          if (target) {
            const next = new Map(intentions);
            next.set(p.intention_id, {
              ...target,
              status: "resolved",
              resolved_at: new Date(env.timestamp_ms).toISOString(),
            });
            intentions = next;
          }
          break;
        }
        case "PIVOT": {
          const p = env.payload as { from_intention_id: string };
          const target = intentions.get(p.from_intention_id);
          if (target) {
            const next = new Map(intentions);
            next.set(p.from_intention_id, { ...target, status: "pivoted" });
            intentions = next;
          }
          break;
        }
        case "CONFLICT": {
          const p = env.payload as { intention_id: string };
          const cur = conflicts.get(p.intention_id) || 0;
          conflicts.set(p.intention_id, cur + 1);
          break;
        }
        case "BELIEF": {
          const p = env.payload as unknown as {
            key: string;
            value: unknown;
            confidence: number;
            source: Belief["source"];
          };
          const next = new Map(beliefs);
          const arr = (next.get(p.key) || []).filter(
            (b) => b.agent_id !== env.agent_id,
          );
          arr.push({
            agent_id: env.agent_id,
            key: p.key,
            value: p.value,
            confidence: p.confidence,
            source: p.source,
            updated_at: new Date(env.timestamp_ms).toISOString(),
          });
          next.set(p.key, arr);
          beliefs = next;
          break;
        }
        case "COST_REPORT": {
          const p = env.payload as { estimated_usd?: number };
          if (typeof p.estimated_usd === "number") {
            costUsd += p.estimated_usd;
          }
          break;
        }
        default:
          break;
      }

      return {
        ...state,
        events,
        intentions,
        beliefs,
        conflictsByIntention: conflicts,
        costUsd,
      };
    }
  }
}

// -----------------------------------------------------------------------------
// Hook: connect to /ws/sessions/{id} via the gateway
// -----------------------------------------------------------------------------
export function useSession(sessionId: string, gatewayWsUrl?: string) {
  const [state, dispatch] = useReducer(reduce, sessionId, initial);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<number>(0);

  useEffect(() => {
    if (!sessionId) return;
    let stopped = false;
    let pingInterval: ReturnType<typeof setInterval> | null = null;

    const url =
      gatewayWsUrl ||
      (typeof window !== "undefined"
        ? `${window.location.protocol === "https:" ? "wss" : "ws"}://${
            window.location.hostname
          }:8000/ws/sessions/${sessionId}`
        : "");

    const connect = () => {
      if (stopped) return;
      const ws = new WebSocket(url);
      wsRef.current = ws;
      ws.onopen = () => {
        dispatch({ kind: "connected", connected: true });
        reconnectRef.current = 0;
        pingInterval = setInterval(() => {
          try {
            ws.send("ping");
          } catch {
            /* ignore */
          }
        }, 20000);
      };
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data) as WSMessage;
          if (data.type === "snapshot") {
            dispatch({ kind: "snapshot", msg: data });
          } else if (data.type === "event") {
            dispatch({ kind: "event", msg: data });
          }
        } catch {
          /* ignore non-JSON (e.g. "pong") */
        }
      };
      ws.onclose = () => {
        if (pingInterval) clearInterval(pingInterval);
        dispatch({ kind: "connected", connected: false });
        if (!stopped) {
          // exponential-ish reconnect
          const delay = Math.min(15000, 500 * 2 ** reconnectRef.current);
          reconnectRef.current += 1;
          setTimeout(connect, delay);
        }
      };
      ws.onerror = () => {
        // Force close so onclose triggers reconnect
        try {
          ws.close();
        } catch {
          /* ignore */
        }
      };
    };

    connect();
    return () => {
      stopped = true;
      if (pingInterval) clearInterval(pingInterval);
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {
          /* ignore */
        }
      }
    };
  }, [sessionId, gatewayWsUrl]);

  return state;
}
