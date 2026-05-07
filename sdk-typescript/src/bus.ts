/**
 * Redis Streams bus client — TypeScript mirror of sdk-python/synapse/bus.py.
 *
 * Stream conventions:
 *   synapse:session:{session_id}:events  — session-wide stream
 *   synapse:agent:{agent_id}:inbox       — per-agent inbox
 */
import Redis, { type RedisOptions } from "ioredis";
import type { Envelope } from "./types.js";

export const sessionStream = (sessionId: string): string =>
  `synapse:session:${sessionId}:events`;

export const agentInbox = (agentId: string): string =>
  `synapse:agent:${agentId}:inbox`;

const DEFAULT_MAXLEN = 10_000;

export interface BusOptions {
  url?: string;          // redis://host:port/db
  redisOptions?: RedisOptions;
  maxLen?: number;
}

export class Bus {
  private redis: Redis | null = null;
  private readonly url: string;
  private readonly redisOptions: RedisOptions | undefined;
  private readonly maxLen: number;

  constructor(opts: BusOptions = {}) {
    this.url = opts.url ?? process.env["SYNAPSE_REDIS_URL"] ?? "redis://localhost:6379/0";
    this.redisOptions = opts.redisOptions;
    this.maxLen = opts.maxLen ?? DEFAULT_MAXLEN;
  }

  async connect(): Promise<void> {
    this.redis = this.redisOptions
      ? new Redis(this.url, this.redisOptions)
      : new Redis(this.url);
    await this.redis.ping();
  }

  async close(): Promise<void> {
    if (this.redis) {
      await this.redis.quit();
      this.redis = null;
    }
  }

  private get r(): Redis {
    if (!this.redis) throw new Error("Bus not connected — call connect() first");
    return this.redis;
  }

  /** Publish to the session stream. Returns the Redis stream entry ID. */
  async publishSession<P>(envelope: Envelope<P>): Promise<string> {
    return this.xadd(sessionStream(envelope.session_id), envelope);
  }

  /** Publish directly to a specific agent's inbox. */
  async publishInbox<P>(agentId: string, envelope: Envelope<P>): Promise<string> {
    return this.xadd(agentInbox(agentId), envelope);
  }

  private async xadd<P>(stream: string, envelope: Envelope<P>): Promise<string> {
    const payload = JSON.stringify(envelope);
    // ioredis: xadd(stream, 'MAXLEN', '~', N, '*', field, value)
    const id = await this.r.xadd(
      stream,
      "MAXLEN",
      "~",
      this.maxLen,
      "*",
      "e",
      payload,
    );
    return id ?? "";
  }

  /** Idempotently create a consumer group at the start of the stream. */
  async ensureGroup(stream: string, group: string): Promise<void> {
    try {
      await this.r.xgroup("CREATE", stream, group, "0", "MKSTREAM");
    } catch (e: unknown) {
      const msg = (e as Error).message ?? "";
      if (!msg.includes("BUSYGROUP")) throw e;
    }
  }

  /**
   * Drain the agent's inbox: read all available messages since lastId and
   * return them. Non-blocking. Returns [entryId, envelope] tuples.
   */
  async drainInbox<P>(
    agentId: string,
    lastId: string = "0",
    count: number = 1000,
  ): Promise<Array<[string, Envelope<P>]>> {
    const stream = agentInbox(agentId);
    const resp = (await this.r.xread("COUNT", count, "STREAMS", stream, lastId)) as
      | Array<[string, Array<[string, string[]]>]>
      | null;
    const out: Array<[string, Envelope<P>]> = [];
    if (!resp) return out;
    for (const [, entries] of resp) {
      for (const [entryId, fields] of entries) {
        const idx = fields.indexOf("e");
        if (idx === -1) continue;
        const raw = fields[idx + 1];
        if (raw === undefined) continue;
        try {
          out.push([entryId, JSON.parse(raw) as Envelope<P>]);
        } catch {
          // skip malformed
        }
      }
    }
    return out;
  }
}
