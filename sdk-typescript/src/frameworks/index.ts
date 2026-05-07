/**
 * Framework adapter directory for Synapse.
 *
 * Each framework adapter self-registers via `registerFramework(...)` from
 * `../install.ts`. Importing this module pulls every adapter so
 * `synapse.install({ framework: "<name>" })` can dispatch to the right one.
 *
 * Adapters shipped:
 *   - "vercel-ai" / "vercel" / "ai" — Vercel AI SDK
 *   - "langgraph" / "langchain" / "langchain.js" — LangGraph.js / LangChain.js
 *   - "paperclip" — Paperclip AI server-side adapter
 */

export {
  synapseTool,
  synapseToolAsync,
  wrapVercelTools,
  getCallback as getVercelAICallback,
  inferScope as inferVercelAIScope,
  _resetVercelAIDefaults,
  _setToolFactory as _setVercelAIToolFactory,
} from "./vercelAI.js";

export type {
  VercelTool,
  VercelToolConfig,
  VercelToolExecute,
  SynapseToolConfig,
  SynapseToolExtras,
  WrapVercelToolsOptions,
  VercelAIInstallOptions,
} from "./vercelAI.js";

// LangGraph.js / LangChain.js adapter
export {
  SynapseLangGraphCallback,
  getCallback as getLangGraphCallback,
  isWriteTool as isLangGraphWriteTool,
  inferScope as inferLangGraphScope,
  agentIdFrom as langGraphAgentIdFrom,
  sessionIdFrom as langGraphSessionIdFrom,
  _resetCallback as _resetLangGraphCallback,
} from "./langgraph.js";

export type { BaseCallbackHandlerLike } from "./langgraph.js";

// Paperclip adapter
export {
  _paperclipDefaults,
  _resetPaperclipDefaults,
} from "./paperclip.js";
export type { PaperclipFrameworkDefaults } from "./paperclip.js";

// OpenClaw adapter
export {
  installOpenClaw,
  wrapExtensionWithSynapse as wrapOpenClawExtension,
  makeSynapseExtension as makeOpenClawSynapseExtension,
  _getOpenClawState,
  _resetOpenClawState,
} from "./openclaw.js";
export type {
  OpenClawExtension,
  OpenClawSynapseOptions,
} from "./openclaw.js";
