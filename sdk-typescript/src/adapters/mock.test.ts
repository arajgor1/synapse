import { describe, expect, it } from "vitest";
import { MockAdapter } from "./mock.js";
import { TenantViolation } from "./base.js";
import type { TenantContext } from "../types.js";

async function readAll(adapter: MockAdapter, handle: { request_id: string; original_messages: Array<Record<string, unknown>>; params: Record<string, unknown>; tenant?: TenantContext }): Promise<string> {
  let out = "";
  for await (const tok of adapter.readTokens(handle)) {
    out += tok.text;
  }
  return out.trim();
}

describe("MockAdapter", () => {
  it("streams the scripted response", async () => {
    const adapter = new MockAdapter({ scriptedResponse: "hello world", delayPerTokenMs: 0 });
    const handle = await adapter.startStream([], {});
    const text = await readAll(adapter, handle);
    expect(text).toBe("hello world");
  });

  it("inject_and_continue produces a continuation", async () => {
    const adapter = new MockAdapter({ scriptedResponse: "one two three", delayPerTokenMs: 0 });
    const handle = await adapter.startStream([], {});
    // read one token then inject
    for await (const _t of adapter.readTokens(handle)) break;
    const newHandle = await adapter.injectAndContinue(handle, "STOP", "Pivot.");
    const text = await readAll(adapter, newHandle);
    expect(text).toContain("acknowledged signal: STOP");
  });

  it("cancel returns the partial output", async () => {
    const adapter = new MockAdapter({ scriptedResponse: "ab cd ef", delayPerTokenMs: 1 });
    const handle = await adapter.startStream([], {});
    for await (const _t of adapter.readTokens(handle)) break;
    const partial = await adapter.cancel(handle);
    expect(partial).toContain("ab");
  });

  it("advertises request_id isolation by default", () => {
    const adapter = new MockAdapter();
    expect(adapter.capabilities.multi_tenant_isolation).toBe("request_id");
  });

  it("rejects cross-tenant read", async () => {
    const adapter = new MockAdapter({ scriptedResponse: "secret", delayPerTokenMs: 0 });
    const owner: TenantContext = { tenant_id: "acme", agent_id: "a1", session_id: "s1" };
    const handle = await adapter.startStream([], { tenant: owner });
    const attackerHandle = {
      ...handle,
      tenant: { tenant_id: "evil" } as TenantContext,
    };
    await expect(async () => {
      for await (const _t of adapter.readTokens(attackerHandle)) {
        // should throw before yielding
      }
    }).rejects.toBeInstanceOf(TenantViolation);
  });

  it("inject_and_continue rejects cross-tenant", async () => {
    const adapter = new MockAdapter({ scriptedResponse: "x", delayPerTokenMs: 0 });
    const owner: TenantContext = { tenant_id: "acme" };
    const handle = await adapter.startStream([], { tenant: owner });
    const attackerHandle = {
      ...handle,
      tenant: { tenant_id: "evil" } as TenantContext,
    };
    await expect(adapter.injectAndContinue(attackerHandle, "x")).rejects.toBeInstanceOf(
      TenantViolation,
    );
  });

  it("anonymous caller can act on anonymous request", async () => {
    const adapter = new MockAdapter({ scriptedResponse: "ok", delayPerTokenMs: 0 });
    const handle = await adapter.startStream([], {});
    const text = await readAll(adapter, handle);
    expect(text).toBe("ok");
  });
});
