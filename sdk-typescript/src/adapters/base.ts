/** InferenceAdapter contract — mirrors spec/adapter.md. */
import type { BackendCapabilities, TenantContext } from "../types.js";

export interface StreamHandle {
  request_id: string;
  original_messages: Array<Record<string, unknown>>;
  params: Record<string, unknown>;
  tenant?: TenantContext;
  /** Adapter-specific extra state (closure refs, fetch controllers, etc.) */
  extra?: Record<string, unknown>;
}

export interface Token {
  text: string;
  is_thinking?: boolean;
  is_boundary?: boolean;
}

export class BackendUnavailable extends Error {}
export class UnsupportedCapability extends Error {}
export class TenantViolation extends Error {}

export interface InferenceAdapter {
  capabilities: BackendCapabilities;

  startStream(
    messages: Array<Record<string, unknown>>,
    params?: Record<string, unknown>,
  ): Promise<StreamHandle>;

  readTokens(handle: StreamHandle): AsyncIterable<Token>;

  injectAndContinue(
    handle: StreamHandle,
    injection: string,
    instruction?: string,
  ): Promise<StreamHandle>;

  cancel(handle: StreamHandle): Promise<string>;
}
