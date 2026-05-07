export * from "./types.js";
export * from "./envelope.js";
export * from "./bus.js";
export * from "./agent.js";
export * from "./adapters/base.js";
export { MockAdapter } from "./adapters/mock.js";

// BYO-LLM (v0.2): config + bridges for Anthropic / OpenAI / Vercel AI / LangChain.js
export {
  type LLMConfig,
  setLlm,
  getLlm,
  getInternalLlm,
  isConfigured,
  clear,
  type BridgeAdapter,
  type ChatMessage,
  type GenerateOptions,
  type FromAnthropicOptions,
  type FromOpenAIOptions,
  type VercelLanguageModelLike,
  type LangChainJSChatModelLike,
  type AutoLlmOptions,
  fromAnthropic,
  fromOpenAI,
  fromVercelAI,
  fromLangChainJS,
  autoLlm,
} from "./llm/index.js";

// Framework integrations
export {
  wrapAdapterWithSynapse,
  makeMockSynapsePaperclipAdapter,
} from "./integrations/paperclip.js";
export type {
  PaperclipAdapter,
  PaperclipTask,
  PaperclipAdapterRequest,
  PaperclipAdapterResponse,
  WrapWithSynapseOptions,
} from "./integrations/paperclip.js";

export {
  wrapExtensionWithSynapse,
  makeSynapseExtension,
} from "./integrations/openclaw.js";
export type {
  OpenClawTool,
  OpenClawExtension,
  OpenClawSynapseOptions,
} from "./integrations/openclaw.js";

// Beliefs — semantic-conflict detection
export {
  emitBelief,
  listDivergences,
  divergencesForKey,
} from "./beliefs/index.js";
export type {
  AgentBelief,
  BeliefDivergence,
  BeliefSource,
  EmitBeliefArgs,
  FactExtraction,
  LiveDivergenceResult,
} from "./beliefs/index.js";

// Merge policies (v0.2)
export {
  MergePolicy,
  MergeDecision,
  SynapseConflict,
  RedirectPolicy,
  WaitPolicy,
  AbortPolicy,
  AutoMergePolicy,
  NoOpPolicy,
  resolvePolicy,
  criticalScopeMatch,
  normalizeCriticalScopes,
} from "./policies/index.js";
export type {
  MergeAction,
  IntentionHandleLike,
  PolicyLike,
} from "./policies/index.js";

// v0.2 foundation: universal intend() + install() bootstrap
export {
  intend,
  intendWith,
  IntentionHandle,
  shutdown,
} from "./intend.js";
export type { IntendOptions, Outcome, SynapseRuntime } from "./intend.js";

export { install, registerFramework } from "./install.js";
export type {
  InstallOptions,
  InstallResult,
  FrameworkInstallFn,
} from "./install.js";

// Framework adapters (self-register on import)
import "./frameworks/index.js";
export * as frameworks from "./frameworks/index.js";

// Direct re-exports of the LangGraph.js / LangChain.js adapter for users
// who want `import { SynapseLangGraphCallback } from "@synapse-protocol/sdk"`.
export {
  SynapseLangGraphCallback,
  getCallback as getLangGraphCallback,
} from "./frameworks/langgraph.js";

// Direct re-exports of the Vercel AI SDK adapter so users can do
// `import { synapseTool, wrapVercelTools } from "@synapse-protocol/sdk"`.
export {
  synapseTool,
  synapseToolAsync,
  wrapVercelTools,
  getCallback as getVercelAICallback,
} from "./frameworks/vercelAI.js";
export type {
  VercelTool,
  VercelToolConfig,
  VercelToolExecute,
  SynapseToolConfig,
  SynapseToolExtras,
  WrapVercelToolsOptions,
  VercelAIInstallOptions,
} from "./frameworks/vercelAI.js";
