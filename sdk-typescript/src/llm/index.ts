/** BYO-LLM configuration for Synapse v0.2 — TypeScript port. */
export {
  type LLMConfig,
  setLlm,
  getLlm,
  getInternalLlm,
  isConfigured,
  clear,
} from "./config.js";

export {
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
} from "./bridges.js";
