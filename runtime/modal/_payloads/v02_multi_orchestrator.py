"""Multi-orchestrator natural workload — the missing experiment.

Two INDEPENDENT teams (orchestrator + 2 workers each) build the same
mini-Stripe project on the same codebase. No shared coordinator. No
shared planning history. Each team's orchestrator picks files
independently — overlapping work is the EXPECTED outcome.

This is the scenario the SDLC benchmark proxied with hand-planted
collisions. Here we let them happen naturally.

Three modes compared:
  no_synapse   — both teams fire and forget; last writer wins
  observer     — Synapse watches with MergePolicy.redirect (warn-only)
                 + emit_beliefs_from_tool_results=True (max detection,
                 zero intervention)
  full         — MergePolicy.auto_merge + emit_beliefs_from_tool_results=True
                 (real intervention)

Goal: see whether Synapse adds DETECTION value (observer) and SAFETY
value (full) when there's no orchestrator pre-deconfliction.
"""
from __future__ import annotations

import os
os.environ["LANGCHAIN_CALLBACKS_BACKGROUND"] = "false"

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from collections import defaultdict

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
    " CREATE TABLE IF NOT EXISTS beliefs ("
    " agent_id text NOT NULL, session_id text NOT NULL, tenant_id text,"
    " key text NOT NULL, value jsonb NOT NULL,"
    " confidence real NOT NULL CHECK (confidence BETWEEN 0 AND 1),"
    " source text NOT NULL CHECK (source IN ('observed','inferred','assumed')),"
    " evidence text, updated_at timestamptz NOT NULL DEFAULT now(),"
    " PRIMARY KEY (agent_id, key)"
    ");"
)


# Each TEAM gets the SAME prompt — that's the point. Two teams independently
# building the same thing without coordination.
TEAM_TASK = """\
You are the lead architect of an AI engineering team building a mini-Stripe
billing platform. The system needs:
  - User accounts with email + password auth
  - Subscriptions (per-seat OR usage-based — your call)
  - Invoices with line items
  - Stripe webhook handling
  - Test coverage on the critical paths

You have 2 worker agents available, each can write 1 file per turn:
  - {backend_id}  (Express + Postgres + bcrypt)
  - {frontend_id} (React + Tailwind admin dashboard)

You decide:
  1. What file each worker writes next
  2. What the file should contain (1-2 line spec)
  3. When to STOP (when you think the system is functionally complete)

Output ONLY valid JSON for each turn:
  {{"thought": "<one-line plan>", "assignments": [
      {{"agent": "{backend_id}", "file": "<path>", "spec": "<1-2 lines>"}}
   ], "done": false}}

When done: {{"thought":"...","assignments":[],"done":true}}.
Be decisive. You are independent — there is no other team to coordinate with.
"""


async def apply_migrations():
    import asyncpg
    conn = await asyncpg.connect(PG_DSN)
    try:
        await conn.execute(MIGRATIONS_SQL)
    finally:
        await conn.close()


async def run_team(
    *, team_name: str, mode: str, ant, repo_root: str, session_id: str,
    backend_id: str, frontend_id: str, orch_id: str,
    capture: dict, max_turns: int = 8,
):
    """One team's autonomous loop. Independent orchestrator, 2 workers."""
    import synapse

    history: list[dict] = []
    print(f"  [{team_name}] starting (orch={orch_id}, workers={backend_id},{frontend_id})", flush=True)

    for turn in range(1, max_turns + 1):
        prompt = TEAM_TASK.format(backend_id=backend_id, frontend_id=frontend_id)
        prompt += f"\n\n## Done so far by {team_name}:\n"
        if not history:
            prompt += "(nothing yet)"
        else:
            for h in history[-6:]:
                prompt += f"- t{h['turn']}: {h['agent']} wrote {h['file']}\n"

        try:
            msg = await ant.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            print(f"  [{team_name}] orchestrator LLM error t{turn}: {e}", flush=True)
            break
        plan_raw = (msg.content[0].text if msg.content else "{}").strip()
        if plan_raw.startswith("```"):
            plan_raw = plan_raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            if plan_raw.startswith("json"):
                plan_raw = plan_raw[4:].strip()

        try:
            plan = json.loads(plan_raw)
        except json.JSONDecodeError:
            print(f"  [{team_name}] t{turn} bad JSON, stopping", flush=True)
            break

        thought = plan.get("thought", "")
        assignments = plan.get("assignments", []) or []
        print(f"  [{team_name}] t{turn} thought: {thought[:80]}", flush=True)

        if plan.get("done") or not assignments:
            print(f"  [{team_name}] declared done at t{turn}", flush=True)
            break

        # Workers run in parallel within the team
        worker_results = await asyncio.gather(*[
            run_worker_call(
                team_name=team_name, assignment=a, mode=mode, ant=ant,
                repo_root=repo_root, session_id=session_id,
            ) for a in assignments
        ], return_exceptions=True)

        for a, r in zip(assignments, worker_results):
            if isinstance(r, Exception):
                print(f"  [{team_name}] worker {a.get('agent')} crashed: {r}", flush=True)
                continue
            history.append({"turn": turn, **a, "outcome": r.get("outcome", "?")})
            capture["history"].append({"team": team_name, "turn": turn, **a, **r})


async def run_worker_call(
    *, team_name: str, assignment: dict, mode: str, ant,
    repo_root: str, session_id: str,
):
    """One file write — wraps in synapse.intend() in observer/full modes."""
    import synapse

    agent_id = assignment.get("agent", "?")
    file_rel = assignment.get("file", f"unknown_{int(time.time()*1000)}.txt")
    spec = assignment.get("spec", "")
    write_path = f"{repo_root}/{file_rel}"

    # Generate file content
    msg = await ant.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user",
                   "content": f"You are {agent_id} on team {team_name}. Write the file {file_rel}.\n"
                              f"Spec: {spec}\n\nOutput ONLY the file contents — no markdown fences. "
                              f"<60 lines."}],
    )
    content = msg.content[0].text if msg.content else ""
    if content.strip().startswith("```"):
        lines = content.strip().split("\n")
        content = "\n".join(lines[1:-1]) if len(lines) >= 2 else content

    proposed = {"path": file_rel, "content": content, "tool": "write_file"}
    scope = [f"repo.fs.{file_rel}:w"]

    if mode == "no_synapse":
        os.makedirs(os.path.dirname(write_path) or ".", exist_ok=True)
        with open(write_path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"outcome": "success", "wrote_bytes": len(content),
                "saw_conflicts": False, "merged": False, "divergences": []}

    async with synapse.intend(
        scope=scope, agent=agent_id, session=session_id,
        expected_outcome=f"{agent_id}@{team_name}: {file_rel}",
        blocking=True, gate_ms=400,  # wider gate for cross-team detection
        proposed_action=proposed,
    ) as i:
        if i.has_conflicts:
            print(f"  ⚠ {team_name}/{agent_id} CONFLICT on {file_rel} ({len(i.conflicts)} priors)", flush=True)
        final_content = content
        merged = False
        if i.merged_action and "content" in i.merged_action:
            final_content = i.merged_action["content"]
            merged = True
            print(f"  🔀 {team_name}/{agent_id} auto_merged {file_rel}", flush=True)

        os.makedirs(os.path.dirname(write_path) or ".", exist_ok=True)
        with open(write_path, "w", encoding="utf-8") as f:
            f.write(final_content)
        i.set_state_diff({"content": final_content[:1500],
                          "wrote_bytes": len(final_content)})
        for d in (i.divergences or []):
            print(f"  💭 BELIEF DIVERGENCE on {d.get('key','?')}: "
                  f"{d.get('distinct_values',[])[:2]}", flush=True)

    return {"outcome": "success", "wrote_bytes": len(final_content),
            "saw_conflicts": i.has_conflicts, "merged": merged,
            "divergences": list(i.divergences or [])}


async def run_one_mode(mode: str, ant) -> dict:
    print(f"\n=== mode: {mode} ===", flush=True)
    session_id = f"v02_multi_{mode}_{uuid.uuid4().hex[:6]}"
    repo_root = f"/tmp/multi_{mode}_{uuid.uuid4().hex[:4]}"
    capture = {"team_files": defaultdict(list), "history": []}

    bus = state = router_task = None
    if mode != "no_synapse":
        import synapse
        synapse.set_llm(synapse.from_anthropic(ant, model="claude-haiku-4-5-20251001"))
        merge_policy = (synapse.MergePolicy.auto_merge if mode == "full"
                        else synapse.MergePolicy.redirect)
        # Always emit beliefs in synapse modes — even observer should detect them
        synapse.install(
            bus_url=REDIS_URL, state_dsn=PG_DSN, session_id=session_id,
            merge_policy=merge_policy,
            emit_beliefs_from_tool_results=True,
        )

        from synapse.bus import Bus
        from synapse.state import StateGraph
        from runtime.router.worker import Router
        bus = Bus(REDIS_URL); state = StateGraph(PG_DSN)
        await bus.connect(); await state.connect()
        router = Router(bus, state, session_id, consumer="v02_multi_router")
        router_task = asyncio.create_task(router.run())
        await asyncio.sleep(0.4)
    else:
        try:
            from synapse.intend import _runtime
            _runtime.clear()
        except Exception:
            pass

    started = time.time()

    # TWO TEAMS RUN IN PARALLEL — that's the experiment
    await asyncio.gather(
        run_team(
            team_name="alpha", mode=mode, ant=ant,
            repo_root=repo_root, session_id=session_id,
            backend_id="alpha_backend", frontend_id="alpha_frontend",
            orch_id="alpha_orch", capture=capture, max_turns=8,
        ),
        run_team(
            team_name="bravo", mode=mode, ant=ant,
            repo_root=repo_root, session_id=session_id,
            backend_id="bravo_backend", frontend_id="bravo_frontend",
            orch_id="bravo_orch", capture=capture, max_turns=8,
        ),
    )

    elapsed = time.time() - started
    await asyncio.sleep(0.6)
    if router_task is not None:
        router.stop()
        try:
            await asyncio.wait_for(router_task, timeout=2)
        except asyncio.TimeoutError:
            router_task.cancel()

    # Compute organic file overlaps
    file_writers = defaultdict(set)
    for h in capture["history"]:
        file_writers[h["file"]].add(h["agent"])
    cross_team_collisions = 0
    same_file_diff_team = []
    for f, agents in file_writers.items():
        teams = set()
        for a in agents:
            teams.add("alpha" if a.startswith("alpha_") else "bravo")
        if len(teams) >= 2:
            cross_team_collisions += 1
            same_file_diff_team.append({"file": f, "agents": sorted(agents)})

    # Pull state graph stats
    intent_count = belief_count = conflict_count = 0
    if mode != "no_synapse" and state is not None and bus is not None:
        intent_rows = await state.pool.fetch(
            "SELECT id FROM intentions WHERE session_id=$1", session_id)
        belief_rows = await state.pool.fetch(
            "SELECT * FROM beliefs WHERE session_id=$1", session_id)
        intent_count = len(intent_rows)
        belief_count = len(belief_rows)
        agent_rows = await state.pool.fetch(
            "SELECT id FROM agents WHERE session_id=$1", session_id)
        for r in agent_rows:
            entries = await bus.redis.xrange(
                f"synapse:agent:{r['id']}:inbox", count=50)
            for _eid, fields in entries:
                try:
                    env = json.loads(fields["e"])
                    if env["type"] == "CONFLICT":
                        conflict_count += 1
                except Exception:
                    pass

    if bus is not None: await bus.close()
    if state is not None: await state.close()

    auto_merges = sum(1 for h in capture["history"] if h.get("merged"))
    divergences_seen = sum(len(h.get("divergences", []))
                            for h in capture["history"])

    print(f"\n  === {mode}: elapsed={elapsed:.1f}s ===", flush=True)
    print(f"  files written by TWO teams (cross-team overlap): {cross_team_collisions}", flush=True)
    if same_file_diff_team:
        for c in same_file_diff_team[:5]:
            print(f"    {c['file']}: {c['agents']}", flush=True)
    print(f"  intentions persisted: {intent_count}", flush=True)
    print(f"  beliefs persisted:    {belief_count}", flush=True)
    print(f"  CONFLICT envelopes:   {conflict_count}", flush=True)
    print(f"  auto_merges:          {auto_merges}", flush=True)
    print(f"  divergences seen:     {divergences_seen}", flush=True)

    return {
        "mode": mode, "session_id": session_id, "repo_root": repo_root,
        "elapsed_seconds": round(elapsed, 2),
        "total_files_written": sum(len(v) for v in file_writers.values()),
        "unique_files": len(file_writers),
        "cross_team_collisions": cross_team_collisions,
        "cross_team_collision_files": same_file_diff_team,
        "intentions_persisted": intent_count,
        "beliefs_persisted": belief_count,
        "conflicts_detected": conflict_count,
        "auto_merges": auto_merges,
        "divergences_seen": divergences_seen,
    }


async def main():
    print("=== v0.2.1 multi-orchestrator natural workload ===", flush=True)
    await apply_migrations()
    from anthropic import AsyncAnthropic
    ant = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    results: dict[str, dict] = {}
    for mode in ("no_synapse", "observer", "full"):
        results[mode] = await run_one_mode(mode, ant)

    print("\n--- summary ---", flush=True)
    for mode, r in results.items():
        print(
            f"  {mode:13s} files={r['unique_files']:2d} "
            f"cross-team-overlap={r['cross_team_collisions']:2d} "
            f"intentions={r['intentions_persisted']:3d} "
            f"conflicts={r['conflicts_detected']:2d} "
            f"merges={r['auto_merges']:2d} "
            f"divergences={r['divergences_seen']:2d} "
            f"elapsed={r['elapsed_seconds']:6.1f}s", flush=True,
        )
    return results


if __name__ == "__main__":
    result = asyncio.run(main())
    print("\n--- result.json ---", flush=True)
    print(json.dumps(result, indent=2, default=str)[:6000], flush=True)
