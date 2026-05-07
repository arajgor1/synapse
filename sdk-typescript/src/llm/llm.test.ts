import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  setLlm,
  getLlm,
  getInternalLlm,
  isConfigured,
  clear,
  fromAnthropic,
  fromOpenAI,
  fromVercelAI,
  fromLangChainJS,
  autoLlm,
} from "./index.js";
import { MockAdapter } from "../adapters/mock.js";

describe("synapse.llm config", () => {
  beforeEach(() => {
    clear();
    // Silence the one-shot console.info "no LLM configured" log during tests.
    vi.spyOn(console, "info").mockImplementation(() => {});
  });

  afterEach(() => {
    clear();
    vi.restoreAllMocks();
  });

  it("setLlm stores adapter and getLlm returns it", () => {
    const m = new MockAdapter();
    setLlm(m);
    expect(getLlm()).toBe(m);
    expect(isConfigured()).toBe(true);
  });

  it("setLlm rejects non-adapters", () => {
    expect(() => setLlm({} as any)).toThrowError(/InferenceAdapter/);
    expect(() => setLlm("hello" as any)).toThrowError(/InferenceAdapter/);
    expect(() => setLlm(null as any)).toThrowError(/InferenceAdapter/);
    expect(() => setLlm(new MockAdapter(), { wrong: true } as any)).toThrowError(
      /InferenceAdapter/,
    );
  });

  it("supports two-LLM split: primary vs internal", () => {
    const primary = new MockAdapter({ scriptedResponse: "primary" });
    const internal = new MockAdapter({ scriptedResponse: "internal" });
    setLlm(primary, internal);
    expect(getLlm()).toBe(primary);
    expect(getInternalLlm()).toBe(internal);
  });

  it("internal falls back to primary when not provided", () => {
    const primary = new MockAdapter();
    setLlm(primary);
    expect(getInternalLlm()).toBe(primary);
  });

  it("offline mode: getLlm/getInternalLlm return null cleanly when unconfigured", () => {
    expect(isConfigured()).toBe(false);
    expect(getLlm()).toBeNull();
    expect(getInternalLlm()).toBeNull();
    // The one-shot info log should have fired exactly once.
    expect(console.info).toHaveBeenCalledTimes(1);
    // Calling again does not re-warn.
    getLlm();
    expect(console.info).toHaveBeenCalledTimes(1);
  });

  it("clear() resets both slots", () => {
    setLlm(new MockAdapter(), new MockAdapter());
    clear();
    expect(getLlm()).toBeNull();
    expect(getInternalLlm()).toBeNull();
    expect(isConfigured()).toBe(false);
  });
});

describe("synapse.llm bridges produce valid adapters", () => {
  beforeEach(() => clear());
  afterEach(() => clear());

  it("fromAnthropic returns an InferenceAdapter (no network call)", () => {
    const a = fromAnthropic({ client: {} as any, model: "claude-haiku-4-5-20251001" });
    expect(a.capabilities.backend_id).toContain("anthropic");
    expect(a.capabilities.tier).toBe("hosted");
    expect(typeof a.startStream).toBe("function");
    expect(typeof a.generate).toBe("function");
    // setLlm should accept it.
    setLlm(a);
    expect(getLlm()).toBe(a);
  });

  it("fromOpenAI returns an InferenceAdapter (no network call)", () => {
    const a = fromOpenAI({ client: {} as any, model: "gpt-4o-mini" });
    expect(a.capabilities.backend_id).toContain("openai");
    setLlm(a);
    expect(getLlm()).toBe(a);
  });

  it("fromVercelAI wraps a LanguageModel and routes to .doGenerate()", async () => {
    const fake = {
      provider: "fake",
      modelId: "fake-1",
      doGenerate: vi.fn(async () => ({ text: "hello from vercel" })),
    };
    const a = fromVercelAI(fake);
    expect(a.capabilities.backend_id).toBe("vercel-ai:fake:fake-1");
    const out = await a.generate({
      messages: [{ role: "user", content: "hi" }],
      maxTokens: 100,
    });
    expect(out).toBe("hello from vercel");
    expect(fake.doGenerate).toHaveBeenCalledOnce();
  });

  it("fromVercelAI rejects objects without doGenerate", () => {
    expect(() => fromVercelAI({} as any)).toThrowError(/doGenerate/);
  });

  it("fromLangChainJS wraps a chat model and routes .generate() through .invoke()", async () => {
    const fakeLLM = {
      _llmType: () => "fake-chat",
      invoke: vi.fn(async () => ({ content: "lc says hi" })),
    };
    const a = fromLangChainJS(fakeLLM);
    expect(a.capabilities.backend_id).toBe("langchain-js:fake-chat");
    const out = await a.generate({
      messages: [
        { role: "system", content: "be brief" },
        { role: "user", content: "hi" },
      ],
    });
    expect(out).toBe("lc says hi");
    expect(fakeLLM.invoke).toHaveBeenCalledOnce();
  });

  it("fromLangChainJS rejects objects without invoke", () => {
    expect(() => fromLangChainJS({} as any)).toThrowError(/invoke/);
  });

  it("bridge adapters reject streaming with UnsupportedCapability", async () => {
    const a = fromAnthropic({ client: {} as any });
    await expect(a.startStream([], {})).rejects.toThrow(/streaming/i);
  });
});

describe("synapse.llm.autoLlm env detection", () => {
  beforeEach(() => clear());
  afterEach(() => clear());

  it("picks Anthropic when ANTHROPIC_API_KEY is set", () => {
    const a = autoLlm({ env: { ANTHROPIC_API_KEY: "sk-ant-x" } });
    expect(a.capabilities.backend_id).toContain("anthropic");
  });

  it("picks OpenAI when only OPENAI_API_KEY is set", () => {
    const a = autoLlm({ env: { OPENAI_API_KEY: "sk-o-x" } });
    expect(a.capabilities.backend_id).toContain("openai");
  });

  it("prefers Anthropic over OpenAI when both are set", () => {
    const a = autoLlm({ env: { ANTHROPIC_API_KEY: "x", OPENAI_API_KEY: "y" } });
    expect(a.capabilities.backend_id).toContain("anthropic");
  });

  it("uses Ollama (OpenAI-compatible) when only OLLAMA_HOST is set", () => {
    const a = autoLlm({ env: { OLLAMA_HOST: "http://localhost:11434" } });
    expect(a.capabilities.backend_id).toContain("openai");
  });

  it("throws when no provider keys are available", () => {
    expect(() => autoLlm({ env: {} })).toThrowError(/no LLM provider keys/);
  });
});
