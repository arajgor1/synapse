"""Real product-dev test: 4 engineering agents collaboratively building
an Instagram-clone FastAPI backend.

This is a realistic multi-agent product-dev workflow — each agent does
3-4 sequential LLM-driven file writes, the way an actual coding agent
(Hermes / Paperclip / OpenClaw / Cursor / Claude Code) would.

Roles + planned files:

  db_engineer:
    models/user.py          (User table: id, username, email, created_at)
    models/post.py          (Post table: id, user_id, image_url, caption, created_at)
    models/like.py          (Like table: id, user_id, post_id)

  api_engineer:
    api/users.py            (GET /users/{id}, POST /users)
    api/posts.py            (POST /posts, GET /posts/{id})
    models/user.py          (** OVERLAPS db_engineer ** — adds bio, avatar_url)

  auth_engineer:
    auth/jwt.py             (token issue + verify)
    auth/password.py        (bcrypt hash + verify)
    models/user.py          (** OVERLAPS db + api ** — adds password_hash, last_login)

  feed_engineer:
    api/feed.py             (GET /feed)
    api/posts.py            (** OVERLAPS api_engineer ** — adds GET /posts feed list)
    services/ranker.py      (chronological + engagement ranking)

Natural collisions:
  - models/user.py        : 3-way collision (db + api + auth all touch)
  - api/posts.py          : 2-way collision (api + feed)

Both modes (no_synapse, with_synapse) call REAL Anthropic Haiku for each
file's content. Synapse mode wraps each write with INTENTION/RESOLUTION
through wrap_tool_call_for_synapse with per-agent attribution.

Measured:
  - total intentions emitted
  - CONFLICT envelopes routed to per-agent inboxes
  - which files actually have multiple contributors (collision evidence)
  - whether the no_synapse run silently overwrites the contended files
  - real LLM token spend
  - elapsed wall time
"""
import asyncio
import json
import os
import random
import sys
import time
import uuid

sys.path.insert(0, "/opt/synapse-sdk")
sys.path.insert(0, "/opt")

REDIS_URL = "redis://localhost:6379/0"
PG_DSN = "postgresql://synapse:synapse_dev@localhost:5432/synapse"

MIGRATIONS_SQL = (
    "CREATE TABLE IF NOT EXISTS agents ("
    " id text PRIMARY KEY, session_id text NOT NULL, tenant_id text,"
    " status text NOT NULL CHECK (status IN ('active','idle','crashed')),"
    " capabilities jsonb NOT NULL,"
    " subscribes text[] NOT NULL DEFAULT '{}',"
    " scopes_owned text[] NOT NULL DEFAULT '{}',"
    " last_heartbeat timestamptz NOT NULL DEFAULT now(),"
    " created_at timestamptz NOT NULL DEFAULT now()"
    ");"
    " CREATE TABLE IF NOT EXISTS intentions ("
    " id text PRIMARY KEY, agent_id text NOT NULL REFERENCES agents(id),"
    " session_id text NOT NULL, tenant_id text, scope text[] NOT NULL,"
    " action jsonb NOT NULL, expected_outcome text NOT NULL,"
    " blocking boolean NOT NULL DEFAULT false,"
    " status text NOT NULL CHECK (status IN ('pending','active','resolved','pivoted')),"
    " created_at timestamptz NOT NULL DEFAULT now(), resolved_at timestamptz"
    ");"
    " CREATE INDEX IF NOT EXISTS intentions_scope_gin ON intentions USING GIN (scope);"
)


# -----------------------------------------------------------------------------
# Workflow plan: 4 specialist agents, each with ~3 sequential file-write tasks
# -----------------------------------------------------------------------------
PLAN = {
    "db_engineer": [
        ("models/user.py",
         "Write a SQLAlchemy User model for an Instagram clone. Class `User`. "
         "Fields: id (PK), username (unique, str), email (unique, str), "
         "created_at (DateTime). Use declarative_base. Output ONLY the Python "
         "class + imports + Base, no prose, no markdown fences."),
        ("models/post.py",
         "Write a SQLAlchemy Post model. Class `Post`. Fields: id (PK), user_id "
         "(FK -> users.id), image_url (str), caption (str, nullable), created_at. "
         "Output ONLY the Python class + imports, no prose, no markdown."),
        ("models/like.py",
         "Write a SQLAlchemy Like model. Class `Like`. Fields: id (PK), user_id "
         "(FK), post_id (FK). Output ONLY the class + imports, no markdown."),
    ],
    "api_engineer": [
        ("api/users.py",
         "Write a FastAPI router for user endpoints. Two routes: "
         "GET /users/{user_id} -> User, POST /users -> User. Use APIRouter. "
         "Output ONLY the Python module, no prose, no markdown."),
        ("api/posts.py",
         "Write a FastAPI router for post endpoints. Two routes: "
         "POST /posts (create), GET /posts/{post_id}. Use APIRouter. "
         "Output ONLY the Python module, no prose."),
        ("models/user.py",
         "Write a SQLAlchemy User model with profile fields the API will read. "
         "Class `User`. Fields: id (PK), username, email, bio (str, nullable), "
         "avatar_url (str, nullable), created_at. Output ONLY the class + "
         "imports + Base, no prose."),
    ],
    "auth_engineer": [
        ("auth/jwt.py",
         "Write JWT token issue + verify helpers using PyJWT. Functions: "
         "create_access_token(user_id) -> str, decode_token(token) -> dict. "
         "Output ONLY the Python module, no prose."),
        ("auth/password.py",
         "Write bcrypt password helpers. Functions: hash_password(pw) -> str, "
         "verify_password(pw, hashed) -> bool. Output ONLY the module, no prose."),
        ("models/user.py",
         "Write a SQLAlchemy User model with auth fields. Class `User`. "
         "Fields: id, username, email, password_hash (str), last_login "
         "(DateTime, nullable), created_at. Output ONLY the class + imports + "
         "Base, no prose."),
    ],
    "feed_engineer": [
        ("api/feed.py",
         "Write a FastAPI router for the home feed. One route: GET /feed -> "
         "list of posts ranked chronologically. Use APIRouter. Output ONLY "
         "the Python module, no prose."),
        ("api/posts.py",
         "Write a FastAPI router for post listing. Routes: GET /posts "
         "(paginated list), GET /posts/{post_id} (single). Use APIRouter. "
         "Output ONLY the Python module, no prose."),
        ("services/ranker.py",
         "Write a ranker service. Function: rank_posts(posts: list, by: str = "
         "'recent') -> list. Two strategies: 'recent' (sort by created_at "
         "desc) and 'engagement' (sort by like_count desc). Output ONLY the "
         "Python module, no prose."),
    ],
}


def scope_for(path: str) -> list[str]:
    safe = path.replace("/", "/").lstrip("/")
    return [f"repo.fs.{safe}:w"]


async def apply_migrations() -> None:
    import asyncpg
    conn = await asyncpg.connect(PG_DSN)
    try:
        await conn.execute(MIGRATIONS_SQL)
    finally:
        await conn.close()


async def agent_workflow(agent_id, session_id, plan, repo_root, ant, with_synapse):
    """Run one specialist's 3-step workflow: real LLM + write each file."""
    from synapse.integrations.hermes_integration import wrap_tool_call_for_synapse

    results = []
    for path, prompt in plan:
        # Small jitter so agents don't all-fire-at-zero (slightly more realistic)
        await asyncio.sleep(random.uniform(0.0, 0.15))

        msg = await ant.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        content = msg.content[0].text if msg.content else ""

        full_path = os.path.join(repo_root, path)

        async def actual_write(fp=full_path, body=content):
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            # Track contributors to detect overwrites
            existed_before = os.path.exists(fp)
            with open(fp, "w", encoding="utf-8") as f:
                f.write(body)
            return {
                "wrote_bytes": len(body),
                "overwrote_existing": existed_before,
            }

        if with_synapse:
            tool_result = await wrap_tool_call_for_synapse(
                "write_file", {"path": path}, actual_write,
                agent_id=agent_id,
            )
        else:
            tool_result = await actual_write()

        results.append({
            "path": path,
            "tool_result": tool_result,
            "tokens_in": msg.usage.input_tokens,
            "tokens_out": msg.usage.output_tokens,
            "content_first_line": (content.splitlines() or [""])[0][:80],
        })
    return {"agent_id": agent_id, "steps": results}


async def run_scenario(with_synapse: bool):
    label = "with_synapse" if with_synapse else "no_synapse"
    print(f"\n=== mode: {label} ===")

    from anthropic import AsyncAnthropic
    from synapse.bus import Bus
    from synapse.state import StateGraph
    from synapse.integrations.hermes_integration import (
        install_hermes_synapse_hooks, register_synapse_agent, _hermes_runtime,
    )

    bus = Bus(REDIS_URL)
    state = StateGraph(PG_DSN)
    await bus.connect()
    await state.connect()
    session_id = f"insta_{label}_{uuid.uuid4().hex[:8]}"

    repo_root = f"/tmp/insta_clone_{label}_{uuid.uuid4().hex[:6]}"
    os.makedirs(repo_root, exist_ok=True)

    router = None
    router_task = None
    if with_synapse:
        await install_hermes_synapse_hooks(
            bus=bus, state=state, session_id=session_id,
            agent_id="db_engineer", gate_ms=400,
        )
        for aid in ("api_engineer", "auth_engineer", "feed_engineer"):
            await register_synapse_agent(aid)
        from runtime.router.worker import Router

        router = Router(bus, state, session_id, consumer="insta_router")
        router_task = asyncio.create_task(router.run())
        await asyncio.sleep(0.4)
    else:
        _hermes_runtime.clear()

    ant = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    started = time.time()
    agent_results = await asyncio.gather(
        *[
            agent_workflow(aid, session_id, plan, repo_root, ant, with_synapse)
            for aid, plan in PLAN.items()
        ],
        return_exceptions=True,
    )
    elapsed = time.time() - started

    # let coordinator/router catch up
    await asyncio.sleep(0.8)

    if router_task is not None:
        router.stop()
        try:
            await asyncio.wait_for(router_task, timeout=2)
        except asyncio.TimeoutError:
            router_task.cancel()

    # Inspect bus + state graph
    intent_rows = []
    agent_rows = []
    stream_entries = []
    inbox_entries = []
    conflict_count = 0
    if with_synapse:
        intent_rows = await state.pool.fetch(
            "SELECT id, agent_id, scope, status FROM intentions WHERE session_id = $1 ORDER BY created_at",
            session_id,
        )
        agent_rows = await state.pool.fetch(
            "SELECT id FROM agents WHERE session_id = $1", session_id,
        )
        redis = bus.redis
        stream_entries = await redis.xrange(
            f"synapse:session:{session_id}:events", count=200,
        )
        for r in agent_rows:
            entries = await redis.xrange(
                f"synapse:agent:{r['id']}:inbox", count=50,
            )
            inbox_entries.extend([(r["id"], e) for e in entries])
        for _aid, (eid, fields) in inbox_entries:
            try:
                env = json.loads(fields["e"])
                if env["type"] == "CONFLICT":
                    conflict_count += 1
            except Exception:
                pass

    # File-level analysis: who wrote each file? was it overwritten?
    file_writes: dict[str, list[str]] = {}
    for r in agent_results:
        if not isinstance(r, dict):
            continue
        for step in r["steps"]:
            file_writes.setdefault(step["path"], []).append(r["agent_id"])

    contended_files = {p: aids for p, aids in file_writes.items() if len(aids) > 1}

    # Inspect final state of each contended file
    final_files = {}
    for path in contended_files:
        full = os.path.join(repo_root, path)
        try:
            with open(full, encoding="utf-8") as f:
                txt = f.read()
            final_files[path] = {
                "bytes": len(txt),
                "first_line": (txt.splitlines() or [""])[0][:100],
            }
        except FileNotFoundError:
            final_files[path] = {"missing": True}

    tokens_in = sum(
        s.get("tokens_in", 0)
        for r in agent_results if isinstance(r, dict)
        for s in r["steps"]
    )
    tokens_out = sum(
        s.get("tokens_out", 0)
        for r in agent_results if isinstance(r, dict)
        for s in r["steps"]
    )
    total_steps = sum(len(r["steps"]) for r in agent_results if isinstance(r, dict))

    print(f"  elapsed:                    {elapsed:.1f}s")
    print(f"  agents:                     {len(PLAN)}")
    print(f"  total file-write steps:     {total_steps}")
    print(f"  unique files written:       {len(file_writes)}")
    print(f"  contended files:            {len(contended_files)}  -> {list(contended_files)}")
    print(f"  contributors per contended file:")
    for p, aids in contended_files.items():
        print(f"      {p:25s} <- {aids}")
    print(f"  tokens in/out:              {tokens_in}/{tokens_out}")
    print(f"  envelopes on bus stream:    {len(stream_entries)}")
    print(f"  intentions persisted (PG):  {len(intent_rows)}")
    print(f"  agents persisted (PG):      {len(agent_rows)}")
    print(f"  CONFLICT envelopes routed:  {conflict_count}")

    await bus.close()
    await state.close()

    return {
        "mode": label,
        "session_id": session_id,
        "elapsed_seconds": round(elapsed, 2),
        "total_steps": total_steps,
        "unique_files": len(file_writes),
        "contended_files": contended_files,
        "final_contended_state": final_files,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "envelopes_on_stream": len(stream_entries),
        "intentions_persisted": len(intent_rows),
        "agents_persisted": len(agent_rows),
        "conflicts_detected": conflict_count,
        "agent_results": [
            r if isinstance(r, dict) else {"error": str(r)} for r in agent_results
        ],
    }


async def main():
    print("=== REAL multi-agent Instagram-clone backend product-dev test ===")
    await apply_migrations()
    no_syn = await run_scenario(with_synapse=False)
    with_syn = await run_scenario(with_synapse=True)
    print("\n--- summary ---")
    print(f"  no_synapse:    steps={no_syn['total_steps']}  "
          f"contended={len(no_syn['contended_files'])}  "
          f"conflicts_caught={no_syn['conflicts_detected']}  "
          f"tokens_out={no_syn['tokens_out']}")
    print(f"  with_synapse:  steps={with_syn['total_steps']}  "
          f"contended={len(with_syn['contended_files'])}  "
          f"conflicts_caught={with_syn['conflicts_detected']}  "
          f"intentions={with_syn['intentions_persisted']}  "
          f"envelopes={with_syn['envelopes_on_stream']}")
    return {"no_synapse": no_syn, "with_synapse": with_syn}


if __name__ == "__main__":
    result = asyncio.run(main())
    print("\n--- result.json ---")
    print(json.dumps(result, indent=2))
