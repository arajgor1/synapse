export type Framework = "Hermes" | "LangGraph" | "CrewAI";

export type AgentStatus = "active" | "deliberating" | "blocked" | "merged";

export interface Agent {
  id: string;
  name: string;
  role: string;
  framework: Framework;
  intention: string;
  status: AgentStatus;
  ticks: number; // intentions emitted this session
}

export type EnvelopeKind = "INTENTION" | "RESOLUTION" | "CONFLICT" | "BELIEF";

export interface Envelope {
  id: string;       // ENV-… short id
  kind: EnvelopeKind;
  agent: string;    // agent name
  scope: string;    // e.g. repo.fs.models/user.py:w
  summary: string;
  ts: string;       // ISO-ish or relative
  age: string;      // e.g. "2s ago"
  meta?: Record<string, string | number>;
}

export interface ConflictDetail {
  id: string;
  scope: string;
  severity: "low" | "med" | "high";
  agentA: { name: string; intention: string };
  agentB: { name: string; intention: string };
  policy: string;          // e.g. auto_merge, defer_to_priority
  resolutionMs: number;
  priors: number;
  status: "auto-merged" | "manual-review" | "deferred";
}

export interface BeliefDivergence {
  key: string;
  type: "scalar" | "string" | "expression";
  values: { agent: string; value: string; confidence: number }[];
  detectedAt: string;
}

// ---- session: ecom_v1 ----

export const sessionMeta = {
  id: "ecom_v1",
  startedAt: "2026-05-07T14:08:21Z",
  uptime: "00:14:32",
  policy: "auto_merge_priors:on / scope_lock:soft",
};

export const kpis = {
  agentsActive: 4,
  intentions: 23,
  conflictsCaught: 7,
  autoMerges: 2,
};

export const agents: Agent[] = [
  {
    id: "a-db",
    name: "db_engineer",
    role: "Schema & migrations",
    framework: "Hermes",
    intention: "extend users table with `last_login_at`",
    status: "active",
    ticks: 6,
  },
  {
    id: "a-api",
    name: "api_engineer",
    role: "Service layer",
    framework: "Hermes",
    intention: "add /v1/auth/refresh handler",
    status: "active",
    ticks: 5,
  },
  {
    id: "a-auth",
    name: "auth_engineer",
    role: "Identity & sessions",
    framework: "Hermes",
    intention: "rotate refresh_token on /refresh",
    status: "deliberating",
    ticks: 4,
  },
  {
    id: "a-clean",
    name: "cleaner",
    role: "Data normalization",
    framework: "Hermes",
    intention: "drop dup orders rows by (order_id, ts)",
    status: "active",
    ticks: 3,
  },
  {
    id: "a-analyst",
    name: "analyst",
    role: "Reporting",
    framework: "Hermes",
    intention: "compute weekly_revenue rollup",
    status: "blocked",
    ticks: 2,
  },
  {
    id: "a-finance",
    name: "finance_lead",
    role: "Cross-checks",
    framework: "Hermes",
    intention: "reconcile revenue against ledger",
    status: "active",
    ticks: 3,
  },
  {
    id: "a-sec",
    name: "lg_security",
    role: "Threat model",
    framework: "LangGraph",
    intention: "scan refresh handler for replay risk",
    status: "deliberating",
    ticks: 2,
  },
  {
    id: "a-crew",
    name: "security_engineer",
    role: "Token policy",
    framework: "CrewAI",
    intention: "propose 7d refresh TTL",
    status: "merged",
    ticks: 1,
  },
];

export const events: Envelope[] = [
  {
    id: "ENV-2c41",
    kind: "INTENTION",
    agent: "db_engineer",
    scope: "repo.fs.models/user.py:w",
    summary: "ALTER users ADD last_login_at TIMESTAMP NULL",
    ts: "14:22:48",
    age: "1s ago",
  },
  {
    id: "ENV-2c40",
    kind: "CONFLICT",
    agent: "auth_engineer",
    scope: "repo.fs.models/user.py:w",
    summary: "stale_base_overwrite — 3 priors not yet observed",
    ts: "14:22:46",
    age: "3s ago",
    meta: { priors: 3, severity: "high" },
  },
  {
    id: "ENV-2c3f",
    kind: "RESOLUTION",
    agent: "synapse.policy",
    scope: "repo.fs.models/user.py:w",
    summary: "auto_merge: 2 priors composed → merged in 1.4s",
    ts: "14:22:44",
    age: "5s ago",
    meta: { strategy: "auto_merge", duration_ms: 1421 },
  },
  {
    id: "ENV-2c3e",
    kind: "INTENTION",
    agent: "api_engineer",
    scope: "src/handlers/auth.py:w",
    summary: "register POST /v1/auth/refresh",
    ts: "14:22:39",
    age: "10s ago",
  },
  {
    id: "ENV-2c3d",
    kind: "BELIEF",
    agent: "analyst",
    scope: "world.metrics.revenue_formula",
    summary: "asserts: revenue = qty*price*(1-discount)",
    ts: "14:22:31",
    age: "18s ago",
    meta: { confidence: 0.82 },
  },
  {
    id: "ENV-2c3c",
    kind: "BELIEF",
    agent: "cleaner",
    scope: "world.metrics.revenue_formula",
    summary: "asserts: revenue = qty*price",
    ts: "14:22:30",
    age: "19s ago",
    meta: { confidence: 0.71 },
  },
  {
    id: "ENV-2c3b",
    kind: "CONFLICT",
    agent: "synapse.policy",
    scope: "src/auth.py:w",
    summary: "scope_overlap on src/auth.py:w (1 active)",
    ts: "14:22:25",
    age: "24s ago",
    meta: { priors: 1, severity: "med" },
  },
  {
    id: "ENV-2c3a",
    kind: "INTENTION",
    agent: "lg_security",
    scope: "src/auth.py:r",
    summary: "read auth.py for replay-attack surface",
    ts: "14:22:18",
    age: "31s ago",
  },
  {
    id: "ENV-2c39",
    kind: "RESOLUTION",
    agent: "synapse.policy",
    scope: "config/policy.yaml",
    summary: "security_engineer 7d TTL accepted (merged into trunk)",
    ts: "14:22:09",
    age: "40s ago",
    meta: { strategy: "accept", duration_ms: 312 },
  },
  {
    id: "ENV-2c38",
    kind: "INTENTION",
    agent: "cleaner",
    scope: "warehouse.tables.orders:w",
    summary: "DELETE FROM orders WHERE rn>1 PARTITION BY (order_id,ts)",
    ts: "14:21:55",
    age: "54s ago",
  },
  {
    id: "ENV-2c37",
    kind: "INTENTION",
    agent: "finance_lead",
    scope: "warehouse.tables.ledger:r",
    summary: "fetch ledger rows for week=2026-W18",
    ts: "14:21:42",
    age: "1m 7s ago",
  },
];

export const activeConflicts: ConflictDetail[] = [
  {
    id: "ENV-2c40",
    scope: "repo.fs.models/user.py:w",
    severity: "high",
    agentA: {
      name: "db_engineer",
      intention: "ALTER users ADD last_login_at TIMESTAMP NULL",
    },
    agentB: {
      name: "auth_engineer",
      intention: "ALTER users ADD refresh_token_hash VARCHAR(128) NOT NULL",
    },
    policy: "stale_base_overwrite",
    resolutionMs: 1421,
    priors: 3,
    status: "auto-merged",
  },
  {
    id: "ENV-2c3b",
    scope: "src/auth.py:w",
    severity: "med",
    agentA: {
      name: "auth_engineer",
      intention: "rotate refresh_token on /refresh",
    },
    agentB: {
      name: "lg_security",
      intention: "wrap /refresh in replay-nonce check",
    },
    policy: "scope_overlap",
    resolutionMs: 0,
    priors: 1,
    status: "manual-review",
  },
];

export const beliefDivergence: BeliefDivergence = {
  key: "world.metrics.revenue_formula",
  type: "expression",
  detectedAt: "14:22:31",
  values: [
    { agent: "cleaner",  value: "qty * price",                 confidence: 0.71 },
    { agent: "analyst",  value: "qty * price * (1 - discount)", confidence: 0.82 },
  ],
};
