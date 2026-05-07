-- Synapse state graph — initial schema
-- Phase 1 deliverable. Captures agents, intentions, beliefs, and blocks.

-- ============================================================
-- agents: registry of all agents currently in any session
-- ============================================================
CREATE TABLE IF NOT EXISTS agents (
  id              text PRIMARY KEY,
  session_id      text NOT NULL,
  tenant_id       text,
  status          text NOT NULL CHECK (status IN ('active', 'idle', 'crashed')),
  capabilities    jsonb NOT NULL,
  subscribes      text[] NOT NULL DEFAULT '{}',
  scopes_owned    text[] NOT NULL DEFAULT '{}',
  last_heartbeat  timestamptz NOT NULL DEFAULT now(),
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agents_session ON agents (session_id);
CREATE INDEX IF NOT EXISTS agents_heartbeat ON agents (last_heartbeat) WHERE status = 'active';

-- ============================================================
-- intentions: live + historical
-- ============================================================
CREATE TABLE IF NOT EXISTS intentions (
  id                text PRIMARY KEY,                            -- ULID
  agent_id          text NOT NULL REFERENCES agents(id),
  session_id        text NOT NULL,
  tenant_id         text,
  scope             text[] NOT NULL,
  action            jsonb NOT NULL,
  expected_outcome  text NOT NULL,
  blocking          boolean NOT NULL DEFAULT false,
  status            text NOT NULL CHECK (status IN ('pending', 'active', 'resolved', 'pivoted')),
  created_at        timestamptz NOT NULL DEFAULT now(),
  resolved_at       timestamptz
);

-- GIN index on scope is the load-bearing index for conflict detection.
-- All conflict queries are scope && scope, which uses this directly.
CREATE INDEX IF NOT EXISTS intentions_scope_gin ON intentions USING GIN (scope);
CREATE INDEX IF NOT EXISTS intentions_active   ON intentions (session_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS intentions_agent    ON intentions (agent_id, status);

-- ============================================================
-- beliefs: per-agent assertions about shared state
-- ============================================================
CREATE TABLE IF NOT EXISTS beliefs (
  agent_id     text NOT NULL,
  session_id   text NOT NULL,
  tenant_id    text,
  key          text NOT NULL,
  value        jsonb NOT NULL,
  confidence   real NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  source       text NOT NULL CHECK (source IN ('observed', 'inferred', 'assumed')),
  evidence     text,
  updated_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (agent_id, key)
);
CREATE INDEX IF NOT EXISTS beliefs_session_key ON beliefs (session_id, key);

-- ============================================================
-- blocks: agents that are currently stuck
-- ============================================================
CREATE TABLE IF NOT EXISTS blocks (
  id           text PRIMARY KEY,
  agent_id     text NOT NULL REFERENCES agents(id),
  session_id   text NOT NULL,
  tenant_id    text,
  blocker      text NOT NULL,
  needed       text NOT NULL,
  attempted    text[] NOT NULL DEFAULT '{}',
  urgency      text NOT NULL CHECK (urgency IN ('low', 'medium', 'high')),
  status       text NOT NULL CHECK (status IN ('open', 'resolved')),
  created_at   timestamptz NOT NULL DEFAULT now(),
  resolved_at  timestamptz
);
CREATE INDEX IF NOT EXISTS blocks_open ON blocks (session_id) WHERE status = 'open';

-- ============================================================
-- events: append-only log of all messages for replay
-- ============================================================
CREATE TABLE IF NOT EXISTS events (
  msg_id       text PRIMARY KEY,                                  -- ULID
  session_id   text NOT NULL,
  tenant_id    text,
  agent_id     text NOT NULL,
  type         text NOT NULL,
  envelope     jsonb NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS events_session_time ON events (session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS events_agent_time   ON events (agent_id, created_at DESC);
