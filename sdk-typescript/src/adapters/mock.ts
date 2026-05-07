/** Mock adapter — scripted streaming, useful for SDK demos and tests. */
import { randomUUID } from "node:crypto";
import type { BackendCapabilities, TenantContext } from "../types.js";
import { tenantsMatch } from "../types.js";
import {
  type InferenceAdapter,
  type StreamHandle,
  type Token,
  TenantViolation,
} from "./base.js";

interface MockState {
  response: string;
  delayPerTokenMs: number;
  cancelled: boolean;
  emittedSoFar: string;
}

export interface MockAdapterOptions {
  scriptedResponse?: string;
  delayPerTokenMs?: number;
  multiTenant?: boolean;
}

export class MockAdapter implements InferenceAdapter {
  capabilities: BackendCapabilities;

  private readonly defaultResponse: string;
  private readonly defaultDelay: number;
  private readonly streams = new Map<string, MockState>();
  private readonly tenantIndex = new Map<string, TenantContext>();

  constructor(opts: MockAdapterOptions = {}) {
    this.defaultResponse = opts.scriptedResponse ?? "Mock response.";
    this.defaultDelay = opts.delayPerTokenMs ?? 5;
    const multiTenant = opts.multiTenant ?? true;
    this.capabilities = {
      backend_id: "mock",
      tier: "native",
      supports_midstream_inject: true,
      supports_partial_preservation: true,
      is_reasoning_model: false,
      prompt_cache_available: false,
      avg_overhead_per_signal: 1.0,
      multi_tenant_isolation: multiTenant ? "request_id" : "process",
      model_id: "mock-llm-1",
    };
  }

  async startStream(
    messages: Array<Record<string, unknown>>,
    params: Record<string, unknown> = {},
  ): Promise<StreamHandle> {
    const requestId = randomUUID().replace(/-/g, "");
    const response = (params["scripted_response"] as string) ?? this.defaultResponse;
    const delay = (params["delay_per_token_ms"] as number) ?? this.defaultDelay;
    this.streams.set(requestId, {
      response,
      delayPerTokenMs: delay,
      cancelled: false,
      emittedSoFar: "",
    });
    const tenant = (params["tenant"] as TenantContext | undefined) ?? {};
    this.tenantIndex.set(requestId, tenant);
    return {
      request_id: requestId,
      original_messages: [...messages],
      params: { ...params },
      tenant,
    };
  }

  readTokens(handle: StreamHandle): AsyncIterable<Token> {
    return this.readTokensImpl(handle);
  }

  private async *readTokensImpl(handle: StreamHandle): AsyncIterable<Token> {
    this.checkTenant(handle);
    const state = this.streams.get(handle.request_id);
    if (!state) throw new Error(`Unknown request: ${handle.request_id}`);
    const words = state.response.split(/\s+/).filter(Boolean);
    for (const w of words) {
      if (state.cancelled) return;
      if (state.delayPerTokenMs > 0) {
        await new Promise((r) => setTimeout(r, state.delayPerTokenMs));
      }
      const piece = w + " ";
      state.emittedSoFar = (state.emittedSoFar + piece).trim();
      yield { text: piece };
    }
  }

  async injectAndContinue(
    handle: StreamHandle,
    injection: string,
    instruction = "Continue, accounting for the above.",
  ): Promise<StreamHandle> {
    this.checkTenant(handle);
    const partial = await this.cancel(handle);
    const newResponse = `[continuing after partial: '${partial.trim()}'] acknowledged signal: ${injection}. ${instruction}`;
    const params: Record<string, unknown> = {
      ...handle.params,
      scripted_response: newResponse,
    };
    if (params["tenant"] === undefined && handle.tenant) {
      params["tenant"] = handle.tenant;
    }
    return this.startStream(handle.original_messages, params);
  }

  async cancel(handle: StreamHandle): Promise<string> {
    this.checkTenant(handle);
    const state = this.streams.get(handle.request_id);
    this.tenantIndex.delete(handle.request_id);
    if (!state) return "";
    state.cancelled = true;
    return state.emittedSoFar;
  }

  private checkTenant(handle: StreamHandle): void {
    const owner = this.tenantIndex.get(handle.request_id);
    if (!owner) return;
    const caller = handle.tenant ?? {};
    if (!tenantsMatch(owner, caller)) {
      throw new TenantViolation(
        `Cross-tenant access on request_id=${handle.request_id}`,
      );
    }
  }
}
