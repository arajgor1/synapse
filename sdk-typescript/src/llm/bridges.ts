/** Bridges from popular vendor clients to Synapse's InferenceAdapter.
 *
 * Each `from*` accepts the vendor's existing client object so the user keeps
 * their model choice, API key, base URL, retry/timeout config, etc., and
 * returns an adapter Synapse can use.
 *
 * These bridges are LIGHTWEIGHT — they expose `.generate()` for Synapse's
 * internal LLM-mediated reasoning paths (scope inference fallback, belief
 * divergence, auto-merge, L3 semantic routing). Streaming methods raise
 * `UnsupportedCapability`; for streaming use a native adapter.
 */
import {
  type InferenceAdapter,
  type StreamHandle,
  type Token,
  UnsupportedCapability,
} from "../adapters/base.js";
import type { BackendCapabilities } from "../types.js";

export interface ChatMessage {
  role: "system" | "user" | "assistant" | string;
  content: string;
}

export interface GenerateOptions {
  messages: ChatMessage[];
  maxTokens?: number;
  temperature?: number;
  [extra: string]: unknown;
}

/** Subset of InferenceAdapter that bridges actually implement.
 *  Exposes `.generate()` in addition to the streaming surface.
 */
export interface BridgeAdapter extends InferenceAdapter {
  generate(opts: GenerateOptions): Promise<string>;
}

// ---------------------------------------------------------------------------
// Shared no-op streaming surface for bridge adapters
// ---------------------------------------------------------------------------
abstract class BaseBridgeAdapter implements BridgeAdapter {
  abstract capabilities: BackendCapabilities;
  abstract generate(opts: GenerateOptions): Promise<string>;

  async startStream(
    _messages: Array<Record<string, unknown>>,
    _params?: Record<string, unknown>,
  ): Promise<StreamHandle> {
    throw new UnsupportedCapability(
      `${this.constructor.name} supports .generate() only. ` +
        "Use a native adapter (e.g. AnthropicAdapter / OpenAIAdapter) for streaming.",
    );
  }

  readTokens(_handle: StreamHandle): AsyncIterable<Token> {
    return (async function* () {
      // empty
    })();
  }

  async injectAndContinue(
    _handle: StreamHandle,
    _injection: string,
    _instruction?: string,
  ): Promise<StreamHandle> {
    throw new UnsupportedCapability(
      `${this.constructor.name} does not support inject_and_continue.`,
    );
  }

  async cancel(_handle: StreamHandle): Promise<string> {
    return "";
  }
}

/** Dynamic-import indirection — hides the specifier from tsc's static analysis
 *  so optional peer deps (`@anthropic-ai/sdk`, `openai`, `@langchain/core`)
 *  don't need to be installed at typecheck time. Resolves at runtime.
 */
const dynamicImport: (specifier: string) => Promise<any> = new Function(
  "s",
  "return import(s)",
) as (specifier: string) => Promise<any>;

function bridgeCapabilities(backendId: string): BackendCapabilities {
  return {
    backend_id: backendId,
    tier: "hosted",
    supports_midstream_inject: false,
    supports_partial_preservation: false,
    is_reasoning_model: false,
    prompt_cache_available: false,
    avg_overhead_per_signal: 0,
    multi_tenant_isolation: "none",
  };
}

// ---------------------------------------------------------------------------
// Anthropic
// ---------------------------------------------------------------------------
export interface FromAnthropicOptions {
  /** A pre-configured `@anthropic-ai/sdk` client (sync or async). Optional. */
  client?: unknown;
  model?: string;
  apiKey?: string;
}

class AnthropicBridgeAdapter extends BaseBridgeAdapter {
  override capabilities: BackendCapabilities;
  private readonly model: string;
  private readonly apiKey: string | undefined;
  private _client: unknown;

  constructor(opts: FromAnthropicOptions) {
    super();
    this.model = opts.model ?? "claude-haiku-4-5-20251001";
    this.apiKey = opts.apiKey;
    this._client = opts.client ?? null;
    this.capabilities = bridgeCapabilities(`anthropic:${this.model}`);
  }

  private async ensureClient(): Promise<{ messages: { create: Function } }> {
    if (this._client !== null && this._client !== undefined) {
      return this._client as { messages: { create: Function } };
    }
    const mod: any = await dynamicImport("@anthropic-ai/sdk").catch((e) => {
      throw new Error(
        "@anthropic-ai/sdk not installed. `npm install @anthropic-ai/sdk`. " +
          `Original error: ${(e as Error).message}`,
      );
    });
    const Anthropic = mod.default ?? mod.Anthropic ?? mod;
    this._client = new Anthropic(
      this.apiKey !== undefined ? { apiKey: this.apiKey } : {},
    );
    return this._client as { messages: { create: Function } };
  }

  override async generate(opts: GenerateOptions): Promise<string> {
    const client = await this.ensureClient();
    const sys = opts.messages
      .filter((m) => m.role === "system")
      .map((m) => m.content)
      .join("\n");
    const nonSystem = opts.messages
      .filter((m) => m.role !== "system")
      .map((m) => ({
        role: m.role === "assistant" ? "assistant" : "user",
        content: m.content,
      }));
    const resp: any = await client.messages.create({
      model: this.model,
      max_tokens: opts.maxTokens ?? 1024,
      temperature: opts.temperature ?? 0,
      ...(sys ? { system: sys } : {}),
      messages: nonSystem,
    });
    const block = resp?.content?.[0];
    if (block && typeof block.text === "string") return block.text;
    return "";
  }
}

export function fromAnthropic(opts: FromAnthropicOptions = {}): BridgeAdapter {
  return new AnthropicBridgeAdapter(opts);
}

// ---------------------------------------------------------------------------
// OpenAI
// ---------------------------------------------------------------------------
export interface FromOpenAIOptions {
  client?: unknown;
  model?: string;
  apiKey?: string;
  baseURL?: string;
}

class OpenAIBridgeAdapter extends BaseBridgeAdapter {
  override capabilities: BackendCapabilities;
  private readonly model: string;
  private readonly apiKey: string | undefined;
  private readonly baseURL: string | undefined;
  private _client: unknown;

  constructor(opts: FromOpenAIOptions) {
    super();
    this.model = opts.model ?? "gpt-4o-mini";
    this.apiKey = opts.apiKey;
    this.baseURL = opts.baseURL;
    this._client = opts.client ?? null;
    this.capabilities = bridgeCapabilities(`openai:${this.model}`);
  }

  private async ensureClient(): Promise<{ chat: { completions: { create: Function } } }> {
    if (this._client !== null && this._client !== undefined) {
      return this._client as { chat: { completions: { create: Function } } };
    }
    const mod: any = await dynamicImport("openai").catch((e) => {
      throw new Error(
        "openai not installed. `npm install openai`. " +
          `Original error: ${(e as Error).message}`,
      );
    });
    const OpenAI = mod.default ?? mod.OpenAI ?? mod;
    const cfg: Record<string, unknown> = {};
    if (this.apiKey !== undefined) cfg["apiKey"] = this.apiKey;
    if (this.baseURL !== undefined) cfg["baseURL"] = this.baseURL;
    this._client = new OpenAI(cfg);
    return this._client as { chat: { completions: { create: Function } } };
  }

  override async generate(opts: GenerateOptions): Promise<string> {
    const client = await this.ensureClient();
    const resp: any = await client.chat.completions.create({
      model: this.model,
      messages: opts.messages.map((m) => ({ role: m.role, content: m.content })),
      max_tokens: opts.maxTokens ?? 1024,
      temperature: opts.temperature ?? 0,
    });
    return resp?.choices?.[0]?.message?.content ?? "";
  }
}

export function fromOpenAI(opts: FromOpenAIOptions = {}): BridgeAdapter {
  return new OpenAIBridgeAdapter(opts);
}

// ---------------------------------------------------------------------------
// Vercel AI SDK (LanguageModel shape: `doGenerate({ prompt, ... })`)
// ---------------------------------------------------------------------------
export interface VercelLanguageModelLike {
  doGenerate: (args: {
    prompt: Array<{ role: string; content: unknown }>;
    maxTokens?: number;
    temperature?: number;
    [extra: string]: unknown;
  }) => Promise<{ text?: string; content?: unknown; [extra: string]: unknown }>;
  modelId?: string;
  provider?: string;
}

class VercelAIBridgeAdapter extends BaseBridgeAdapter {
  override capabilities: BackendCapabilities;
  private readonly model: VercelLanguageModelLike;

  constructor(model: VercelLanguageModelLike) {
    super();
    this.model = model;
    const id =
      [model.provider, model.modelId].filter(Boolean).join(":") || "vercel-ai";
    this.capabilities = bridgeCapabilities(`vercel-ai:${id}`);
  }

  override async generate(opts: GenerateOptions): Promise<string> {
    // Vercel AI SDK v3+ accepts a `prompt` of typed messages where each message
    // has `role` and `content` (content may be a string or a parts array).
    const prompt = opts.messages.map((m) => ({
      role: m.role,
      content: [{ type: "text", text: m.content }],
    }));
    const result = await this.model.doGenerate({
      prompt,
      ...(opts.maxTokens !== undefined ? { maxTokens: opts.maxTokens } : {}),
      ...(opts.temperature !== undefined ? { temperature: opts.temperature } : {}),
    });
    if (typeof result.text === "string") return result.text;
    // Fallback: some implementations return a `content` array of {type,text} parts.
    if (Array.isArray(result.content)) {
      return result.content
        .map((p: any) => (typeof p?.text === "string" ? p.text : ""))
        .join("");
    }
    return "";
  }
}

/** Wrap a Vercel AI SDK `LanguageModel` (anything exposing `doGenerate`). */
export function fromVercelAI(model: VercelLanguageModelLike): BridgeAdapter {
  if (model === null || typeof model !== "object" || typeof model.doGenerate !== "function") {
    throw new TypeError(
      "fromVercelAI expects a Vercel AI SDK LanguageModel (object with `doGenerate`).",
    );
  }
  return new VercelAIBridgeAdapter(model);
}

// ---------------------------------------------------------------------------
// LangChain.js
// ---------------------------------------------------------------------------
export interface LangChainJSChatModelLike {
  invoke: (
    messages: Array<unknown>,
    options?: Record<string, unknown>,
  ) => Promise<{ content?: unknown; text?: unknown; [extra: string]: unknown }>;
  _llmType?: () => string;
  _modelType?: () => string;
}

class LangChainJSBridgeAdapter extends BaseBridgeAdapter {
  override capabilities: BackendCapabilities;
  private readonly llm: LangChainJSChatModelLike;

  constructor(llm: LangChainJSChatModelLike) {
    super();
    this.llm = llm;
    const id =
      (typeof llm._llmType === "function" && llm._llmType()) ||
      (typeof llm._modelType === "function" && llm._modelType()) ||
      llm.constructor?.name ||
      "model";
    this.capabilities = bridgeCapabilities(`langchain-js:${id}`);
  }

  override async generate(opts: GenerateOptions): Promise<string> {
    // Try to use proper LangChain message classes if available; otherwise
    // fall back to the plain {role, content} shape that most LangChain.js
    // chat models also accept.
    let lcMessages: unknown[];
    try {
      const mod: any = await dynamicImport("@langchain/core/messages");
      lcMessages = opts.messages.map((m) => {
        if (m.role === "system") return new mod.SystemMessage(m.content);
        if (m.role === "assistant") return new mod.AIMessage(m.content);
        return new mod.HumanMessage(m.content);
      });
    } catch {
      lcMessages = opts.messages.map((m) => ({ role: m.role, content: m.content }));
    }

    const result: any = await this.llm.invoke(lcMessages);
    if (typeof result?.content === "string") return result.content;
    if (Array.isArray(result?.content)) {
      return result.content
        .map((p: any) => (typeof p?.text === "string" ? p.text : ""))
        .join("");
    }
    if (typeof result?.text === "string") return result.text;
    return String(result ?? "");
  }
}

export function fromLangChainJS(llm: LangChainJSChatModelLike): BridgeAdapter {
  if (llm === null || typeof llm !== "object" || typeof llm.invoke !== "function") {
    throw new TypeError(
      "fromLangChainJS expects a LangChain.js BaseChatModel (object with `invoke`).",
    );
  }
  return new LangChainJSBridgeAdapter(llm);
}

// ---------------------------------------------------------------------------
// Auto-detect (best-effort) — picks the first provider it finds keys for.
// Order: Anthropic → OpenAI → Vercel AI (any AI_* key) → Ollama (local).
// ---------------------------------------------------------------------------
export interface AutoLlmOptions {
  /** Override `process.env` (mostly for tests). */
  env?: Record<string, string | undefined>;
}

export function autoLlm(opts: AutoLlmOptions = {}): BridgeAdapter {
  const env = opts.env ?? (typeof process !== "undefined" ? process.env : {});
  if (env["ANTHROPIC_API_KEY"]) {
    return fromAnthropic({ model: "claude-haiku-4-5-20251001" });
  }
  if (env["OPENAI_API_KEY"]) {
    return fromOpenAI({ model: "gpt-4o-mini" });
  }
  if (env["AI_GATEWAY_API_KEY"] || env["VERCEL_AI_API_KEY"]) {
    // Vercel AI SDK requires a user-provided LanguageModel — we can't fabricate
    // one without the SDK's provider modules. Emit a clear error pointing the
    // user at fromVercelAI(model).
    throw new Error(
      "synapse.autoLlm: detected Vercel AI env keys but Vercel AI requires an " +
        "explicit LanguageModel. Call synapse.fromVercelAI(model) yourself.",
    );
  }
  if (env["OLLAMA_HOST"]) {
    return fromOpenAI({
      model: "llama3.1:8b",
      baseURL: `${env["OLLAMA_HOST"]}/v1`,
      apiKey: "ollama",
    });
  }
  throw new Error(
    "synapse.autoLlm: no LLM provider keys found in environment. " +
      "Set ANTHROPIC_API_KEY / OPENAI_API_KEY / OLLAMA_HOST, or call " +
      "synapse.setLlm(...) explicitly.",
  );
}
