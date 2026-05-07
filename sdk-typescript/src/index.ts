export * from "./types.js";
export * from "./envelope.js";
export * from "./bus.js";
export * from "./agent.js";
export * from "./adapters/base.js";
export { MockAdapter } from "./adapters/mock.js";

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
