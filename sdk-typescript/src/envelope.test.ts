import { describe, expect, it } from "vitest";
import { isUlid, makeEnvelope } from "./envelope.js";
import type { Intention } from "./types.js";

describe("makeEnvelope", () => {
  it("produces a valid ULID for msg_id", () => {
    const env = makeEnvelope<{ scope: string[] }>({
      type: "INTENTION",
      agentId: "a",
      sessionId: "s",
      payload: { scope: ["x:w"] },
    });
    expect(env.msg_id).toHaveLength(26);
    expect(isUlid(env.msg_id)).toBe(true);
  });

  it("sets timestamp_ms close to Date.now()", () => {
    const before = Date.now();
    const env = makeEnvelope({
      type: "INTENTION",
      agentId: "a",
      sessionId: "s",
      payload: {},
    });
    const after = Date.now();
    expect(env.timestamp_ms).toBeGreaterThanOrEqual(before);
    expect(env.timestamp_ms).toBeLessThanOrEqual(after);
  });

  it("omits optional fields when not provided", () => {
    const env = makeEnvelope({
      type: "INTENTION",
      agentId: "a",
      sessionId: "s",
      payload: {},
    });
    expect(env.task_id).toBeUndefined();
    expect(env.tenant_id).toBeUndefined();
  });

  it("propagates tenant_id when provided", () => {
    const env = makeEnvelope({
      type: "INTENTION",
      agentId: "a",
      sessionId: "s",
      payload: {},
      tenantId: "acme",
    });
    expect(env.tenant_id).toBe("acme");
  });

  it("typed payload is preserved", () => {
    const env = makeEnvelope<Intention>({
      type: "INTENTION",
      agentId: "a",
      sessionId: "s",
      payload: {
        action: { tool: "edit", args: {} },
        scope: ["a:w"],
        expected_outcome: "test",
      },
    });
    expect(env.payload.scope).toEqual(["a:w"]);
  });
});

describe("isUlid", () => {
  it("accepts a real ULID", () => {
    expect(isUlid("01HQ2K3M4N5P6R7S8T9V0W1X2Y")).toBe(true);
  });
  it("rejects too-short strings", () => {
    expect(isUlid("01HQ")).toBe(false);
  });
  it("rejects lowercase or invalid chars", () => {
    expect(isUlid("01hq2k3m4n5p6r7s8t9v0w1x2y")).toBe(false);
    expect(isUlid("01HQ2K3M4N5P6R7S8T9V0W1X2I")).toBe(false); // 'I' not in Crockford
  });
});
