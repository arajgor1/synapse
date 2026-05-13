// Vendor metadata for the 10 framework adapters Synapse supports.
// Used to put a human-readable display name + 2-letter badge next to
// every envelope and every artifact card on the cooperative-build view.

export interface Vendor {
  key: string;          // adapter slug (matches role names in v32 bundle)
  name: string;         // human display
  vendor: string;       // company / org
  badge: string;        // 2-letter monogram for the card
  hue: string;          // tailwind text color class for the badge
}

export const VENDORS: Record<string, Vendor> = {
  autogen:       { key: "autogen",       name: "AutoGen",          vendor: "Microsoft",            badge: "MS", hue: "text-accent-blue"   },
  crewai:        { key: "crewai",        name: "CrewAI",           vendor: "CrewAI",               badge: "CW", hue: "text-accent-amber"  },
  langgraph:     { key: "langgraph",     name: "LangGraph",        vendor: "LangChain",            badge: "LC", hue: "text-accent-green"  },
  hermes:        { key: "hermes",        name: "Hermes",           vendor: "Synapse-native",       badge: "HM", hue: "text-accent-violet" },
  smolagents:    { key: "smolagents",    name: "smolagents",       vendor: "HuggingFace",          badge: "HF", hue: "text-accent-amber"  },
  agno:          { key: "agno",          name: "Agno",             vendor: "Agno",                 badge: "AG", hue: "text-accent-blue"   },
  llama_index:   { key: "llama_index",   name: "LlamaIndex",       vendor: "LlamaIndex",           badge: "LI", hue: "text-accent-violet" },
  pydantic_ai:   { key: "pydantic_ai",   name: "Pydantic AI",      vendor: "Pydantic",             badge: "PY", hue: "text-accent-red"    },
  openai_agents: { key: "openai_agents", name: "OpenAI Agents SDK", vendor: "OpenAI",              badge: "OA", hue: "text-accent-green"  },
  google_adk:    { key: "google_adk",    name: "Google ADK",        vendor: "Google",              badge: "GG", hue: "text-accent-blue"   },
};

export const ROLE_TITLE: Record<string, string> = {
  autogen:       "API Architect",
  crewai:        "Backend Engineer",
  langgraph:     "Test Writer",
  hermes:        "Project Coordinator",
  smolagents:    "DB Modeler",
  agno:          "Docs Writer",
  llama_index:   "Lint Reviewer",
  pydantic_ai:   "Schema Validator",
  openai_agents: "Deploy Engineer",
  google_adk:    "Final Reviewer",
};

// Reverse lookup: given a Synapse `agent_id` from an envelope, infer which
// vendor adapter likely emitted it. The v32 bundle has agent_ids like
// "autogen_default", "backend_engineer" (crewai), "tools" (langgraph), etc.
const AGENT_ID_TO_VENDOR: Array<[RegExp, string]> = [
  [/^autogen/i,             "autogen"],
  [/backend_engineer/i,     "crewai"],
  [/^tools$/i,              "langgraph"],     // LangGraph's ToolNode reports as "tools"
  [/coordinator/i,          "hermes"],
  [/^smolagents/i,          "smolagents"],
  [/^agno/i,                "agno"],
  [/^llama_index|^lint/i,   "llama_index"],
  [/schema_validator|^agent$/i, "pydantic_ai"], // pydantic_ai default agent id
  [/deploy_engineer|^openai_agents/i, "openai_agents"],
  [/final_reviewer|^google_adk/i, "google_adk"],
];

export function vendorForAgentId(agentId: string): Vendor | null {
  for (const [pat, key] of AGENT_ID_TO_VENDOR) {
    if (pat.test(agentId)) return VENDORS[key] ?? null;
  }
  return null;
}

export const ORDERED_KEYS: string[] = [
  "autogen", "crewai", "langgraph", "hermes", "smolagents",
  "agno", "llama_index", "pydantic_ai", "openai_agents", "google_adk",
];
