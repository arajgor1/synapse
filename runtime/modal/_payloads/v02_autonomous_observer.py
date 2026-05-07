"""Autonomous observer test for Synapse v0.2.

Unlike the scripted SDLC benchmark (v02_sdlc_billing.py), this one is
*genuinely autonomous*: a single LangGraph orchestrator + worker pool
where the orchestrator decides what to build next based on what's been
done so far, spawns sub-tasks, and lets workers choose their own files.
Synapse runs in OBSERVER mode (failOnConflict=false, MergePolicy.redirect)
so it never interferes with the agentic loop — we just watch what
happens.

Two modes are run for comparison:
  observer   — synapse.intend() emits envelopes but never blocks/merges
  full       — synapse.intend() with MergePolicy.auto_merge active

Real product to build: mini-Stripe billing platform (subscriptions,
invoices, webhooks, admin dashboard, tests). The orchestrator gets ONE
prompt — "build a working Express + Postgres mini-Stripe with these
features" — and decides everything else.

Captures everything for the screen-recording deliverables:
  - asciinema-style stdout transcript (all agent thoughts + tool calls
    + Synapse warnings interleaved with timestamps)
  - structured timeline JSON for the dashboard's replay view
  - filesystem snapshots before/after each tool call (so we can show a
    "files appearing" animation later)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

# Run LangChain async callbacks INLINE
os.environ["LANGCHAIN_CALLBACKS_BACKGROUND"] = "false"

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

# Top-level prompt for the autonomous orchestrator. Deliberately
# under-specified — we want the orchestrator to make real planning
# decisions, not follow a script.
TOP_LEVEL_TASK = """\
You are the lead architect of an AI engineering team building a mini-Stripe
billing platform. The system needs:
  - User accounts with email + password auth
  - Tenants/organizations (multi-tenant)
  - Subscriptions (per-seat OR usage-based pricing — your call)
  - Invoices with line items
  - Stripe webhook handling
  - Admin dashboard (React) showing tenants + subscriptions
  - Test coverage on the critical paths

You have 4 worker agents available, each can write 1 file per turn. Workers:
  - backend_engineer  (Express + Postgres + bcrypt)
  - integrations_engineer  (Stripe SDK + webhook handlers)
  - frontend_engineer  (React + Tailwind admin dashboard)
  - qa_engineer  (Jest + supertest)

You decide:
  1. What file each worker writes next
  2. What the file should contain
  3. When to STOP (when you think the system is functionally complete)

Output ONLY valid JSON for each turn:
  {"thought": "<one-line plan>", "assignments": [
      {"agent": "backend_engineer", "file": "<path>", "spec": "<what to write, 1-2 lines>"}
   ], "done": false}

When the system is complete, output {"thought":"...","assignments":[],"done":true}.

Be decisive. Don't over-plan. The team's coherence is YOUR responsibility.
"""


# -----------------------------------------------------------------------------
# Capture infrastructure: every event becomes a structured timeline entry
# -----------------------------------------------------------------------------
class TimelineCapture:
    """Records every observable event during the autonomous run.

    Three streams:
      - asciinema_lines: stdout-style human-readable transcript with timestamps
      - timeline: structured JSON events for the dashboard replay
      - file_snapshots: filesystem state before/after each tool call
    """

    def __init__(self, run_id: str, mode: str):
        self.run_id = run_id
        self.mode = mode
        self.t0 = time.time()
        self.asciinema_lines: list[dict] = []  # {"t": float, "line": str}
        self.timeline: list[dict] = []         # structured events
        self.file_snapshots: list[dict] = []   # {"t", "path", "phase", "size", "preview"}

    def _t(self) -> float:
        return round(time.time() - self.t0, 3)

    def log(self, line: str, kind: str = "info") -> None:
        """Add a line to the asciinema-style transcript + print to stdout."""
        ts = self._t()
        self.asciinema_lines.append({"t": ts, "line": line, "kind": kind})
        prefix = {
            "info": "  ",
            "agent": "🤖",
            "tool": "🔧",
            "synapse": "🔗",
            "conflict": "⚠️ ",
            "merge": "🔀",
            "belief": "💭",
            "system": "▸ ",
        }.get(kind, "  ")
        print(f"[{ts:7.3f}s] {prefix}{line}", flush=True)

    def event(self, kind: str, **payload) -> None:
        """Add a structured timeline event."""
        self.timeline.append({"t": self._t(), "kind": kind, **payload})

    def snapshot_file(self, path: str, phase: str) -> None:
        """Record file state before/after a tool call."""
        try:
            content = Path(path).read_text(encoding="utf-8")
            self.file_snapshots.append({
                "t": self._t(), "path": path, "phase": phase,
                "size": len(content),
                "preview": content[:300],
            })
        except FileNotFoundError:
            self.file_snapshots.append({
                "t": self._t(), "path": path, "phase": phase,
                "size": 0, "preview": "(missing)",
            })

    def export(self, dest_dir: str) -> dict:
        """Write all captures to disk. Returns a summary."""
        os.makedirs(dest_dir, exist_ok=True)
        run_label = f"{self.run_id}_{self.mode}"

        # asciinema-flavored transcript
        cast_path = f"{dest_dir}/{run_label}.cast"
        with open(cast_path, "w", encoding="utf-8") as f:
            header = {
                "version": 2, "width": 120, "height": 40,
                "timestamp": int(time.time()),
                "title": f"Synapse autonomous observer ({self.mode})",
                "env": {"TERM": "xterm-256color"},
            }
            f.write(json.dumps(header) + "\n")
            for entry in self.asciinema_lines:
                line = entry["line"].replace("\r", "").rstrip() + "\r\n"
                f.write(json.dumps([entry["t"], "o", line]) + "\n")

        # Structured timeline (for the dashboard replay)
        timeline_path = f"{dest_dir}/{run_label}_timeline.json"
        with open(timeline_path, "w", encoding="utf-8") as f:
            json.dump({
                "run_id": self.run_id,
                "mode": self.mode,
                "duration_s": self._t(),
                "events": self.timeline,
            }, f, indent=2)

        # Filesystem snapshots
        snap_path = f"{dest_dir}/{run_label}_snapshots.json"
        with open(snap_path, "w", encoding="utf-8") as f:
            json.dump(self.file_snapshots, f, indent=2)

        return {
            "cast": cast_path,
            "timeline": timeline_path,
            "snapshots": snap_path,
            "events": len(self.timeline),
            "lines": len(self.asciinema_lines),
            "snapshots_count": len(self.file_snapshots),
        }


# -----------------------------------------------------------------------------
# Autonomous orchestrator + workers
# -----------------------------------------------------------------------------
async def run_orchestrator(
    *, mode: str, ant, capture: TimelineCapture,
    repo_root: str, session_id: str, max_turns: int = 12,
) -> dict:
    """One-pass autonomous loop. Orchestrator plans turn by turn."""
    import synapse

    capture.log(f"=== mode: {mode} ===", kind="system")
    capture.log(f"session_id: {session_id}", kind="system")
    capture.log(f"repo_root: {repo_root}", kind="system")
    capture.log(f"top-level task assigned to orchestrator", kind="agent")

    history: list[dict] = []  # what's been done so far
    files_written: dict[str, str] = {}  # path -> last writer

    for turn in range(1, max_turns + 1):
        # 1. Orchestrator chooses what to do this turn
        orchestrator_prompt = TOP_LEVEL_TASK + "\n\n## Done so far:\n"
        if not history:
            orchestrator_prompt += "(nothing yet — pick the first batch of files)"
        else:
            for h in history[-8:]:  # last 8 entries to keep context bounded
                orchestrator_prompt += (
                    f"- turn {h['turn']}: {h['agent']} wrote {h['file']} "
                    f"(spec: {h['spec'][:60]})\n"
                )

        capture.log(f"turn {turn}: orchestrator planning...", kind="agent")
        msg = await ant.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": orchestrator_prompt}],
        )
        plan_raw = msg.content[0].text if msg.content else "{}"
        # Strip markdown fences if any
        plan_raw = plan_raw.strip()
        if plan_raw.startswith("```"):
            plan_raw = plan_raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            if plan_raw.startswith("json"):
                plan_raw = plan_raw[4:].strip()
        try:
            plan = json.loads(plan_raw)
        except json.JSONDecodeError:
            capture.log(
                f"turn {turn}: orchestrator returned invalid JSON, stopping",
                kind="system",
            )
            capture.event("orchestrator_parse_error", turn=turn, raw=plan_raw[:300])
            break

        thought = plan.get("thought", "")
        assignments = plan.get("assignments", []) or []
        capture.log(f"turn {turn}: plan = {thought!r}", kind="agent")
        capture.event(
            "orchestrator_plan", turn=turn, thought=thought,
            assignments=assignments, done=plan.get("done", False),
        )

        if plan.get("done") or not assignments:
            capture.log(f"turn {turn}: orchestrator declared done", kind="agent")
            break

        # 2. Workers execute their assignments in parallel
        worker_results = await asyncio.gather(*[
            run_worker(
                assignment=a, mode=mode, ant=ant,
                capture=capture, repo_root=repo_root, session_id=session_id,
                turn=turn, files_written=files_written,
            )
            for a in assignments
        ], return_exceptions=True)

        for a, r in zip(assignments, worker_results):
            if isinstance(r, Exception):
                capture.log(
                    f"  worker {a.get('agent','?')} crashed: {r}", kind="system",
                )
                continue
            history.append({
                "turn": turn, "agent": a["agent"],
                "file": a.get("file", "?"),
                "spec": a.get("spec", ""),
                "outcome": r.get("outcome", "?"),
            })

    # Compute end-state metrics
    return {
        "turns_completed": turn,
        "files_written": dict(files_written),
        "history": history,
    }


async def run_worker(
    *, assignment: dict, mode: str, ant, capture: TimelineCapture,
    repo_root: str, session_id: str, turn: int,
    files_written: dict[str, str],
) -> dict:
    """One worker generates content for one file via LLM + writes it."""
    import synapse

    agent_id = assignment.get("agent", "unknown")
    file_rel = assignment.get("file", f"unknown_{turn}.txt")
    spec = assignment.get("spec", "")
    write_path = f"{repo_root}/{file_rel}"

    capture.log(
        f"  {agent_id} → {file_rel}  ({spec[:50]})", kind="tool",
    )
    capture.event(
        "worker_start", turn=turn, agent=agent_id,
        file=file_rel, spec=spec,
    )

    # Snapshot before
    capture.snapshot_file(write_path, phase="before")

    # 1. Worker LLM generates the file content
    worker_prompt = (
        f"You are {agent_id}. Write the file {file_rel}.\n"
        f"Spec: {spec}\n\n"
        f"Output ONLY the file's contents — no explanation, no markdown fences. "
        f"Keep it under 60 lines. Be CONCRETE — actual code, not pseudocode."
    )
    msg = await ant.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        messages=[{"role": "user", "content": worker_prompt}],
    )
    content = msg.content[0].text if msg.content else ""

    # Strip wrapping fences if present
    if content.strip().startswith("```"):
        lines = content.strip().split("\n")
        content = "\n".join(lines[1:-1]) if len(lines) >= 2 else content

    # 2. Wrap the actual write through synapse.intend (or skip in no_synapse mode)
    proposed = {"path": file_rel, "content": content, "tool": "write_file"}
    scope = [f"repo.fs.{file_rel}:w"]

    if mode == "no_synapse":
        # Bypass Synapse entirely — direct write, last writer wins
        os.makedirs(os.path.dirname(write_path) or ".", exist_ok=True)
        with open(write_path, "w", encoding="utf-8") as f:
            f.write(content)
        outcome = "success"
    else:
        # Both observer and full modes go through intend()
        async with synapse.intend(
            scope=scope, agent=agent_id, session=session_id,
            expected_outcome=f"{agent_id} writes {file_rel}",
            blocking=True, gate_ms=300,
            proposed_action=proposed,
        ) as i:
            if i.has_conflicts:
                capture.log(
                    f"  ⚠ {agent_id} CONFLICT on {file_rel} ({len(i.conflicts)} priors)",
                    kind="conflict",
                )
                capture.event(
                    "conflict_detected", turn=turn, agent=agent_id,
                    file=file_rel, n_conflicts=len(i.conflicts),
                )

            # If auto_merge merged, use the merged content
            final_content = content
            if i.merged_action and "content" in i.merged_action:
                final_content = i.merged_action["content"]
                capture.log(
                    f"  🔀 auto_merge produced new content for {file_rel}",
                    kind="merge",
                )
                capture.event(
                    "auto_merge", turn=turn, agent=agent_id,
                    file=file_rel,
                    rationale=i.policy_rationale or "",
                )

            os.makedirs(os.path.dirname(write_path) or ".", exist_ok=True)
            with open(write_path, "w", encoding="utf-8") as f:
                f.write(final_content)
            i.set_state_diff({
                "content": final_content[:1500], "wrote_bytes": len(final_content),
            })
            outcome = "success"
            for d in (i.divergences or []):
                capture.log(
                    f"  💭 BELIEF DIVERGENCE on {d.get('key','?')}: "
                    f"{d.get('distinct_values',[])[:60]}",
                    kind="belief",
                )
                capture.event(
                    "belief_divergence", turn=turn, agent=agent_id,
                    key=d.get("key"), values=d.get("distinct_values"),
                    severity=d.get("severity"),
                )

    files_written[file_rel] = agent_id

    # Snapshot after
    capture.snapshot_file(write_path, phase="after")

    return {"agent": agent_id, "file": file_rel, "outcome": outcome,
            "tokens_in": msg.usage.input_tokens,
            "tokens_out": msg.usage.output_tokens}


# -----------------------------------------------------------------------------
# Entry: run both modes, dump captures
# -----------------------------------------------------------------------------
async def apply_migrations():
    import asyncpg
    conn = await asyncpg.connect(PG_DSN)
    try:
        await conn.execute(MIGRATIONS_SQL)
    finally:
        await conn.close()


async def run_one_mode(mode: str, ant, dest_dir: str) -> dict:
    run_id = f"auto_{int(time.time())}"
    session_id = f"v02_auto_{mode}_{uuid.uuid4().hex[:6]}"
    repo_root = f"/tmp/auto_{mode}_{uuid.uuid4().hex[:4]}"
    capture = TimelineCapture(run_id=run_id, mode=mode)

    # Set up Synapse for observer / full modes
    bus = state = router_task = None
    if mode != "no_synapse":
        import synapse
        synapse.set_llm(synapse.from_anthropic(ant, model="claude-haiku-4-5-20251001"))
        merge_policy = (
            synapse.MergePolicy.auto_merge if mode == "full"
            else synapse.MergePolicy.redirect  # observer mode = warn-only
        )
        result = synapse.install(
            bus_url=REDIS_URL, state_dsn=PG_DSN,
            session_id=session_id,
            merge_policy=merge_policy,
            critical_scopes=["billing.*", "stripe.*"],
            emit_beliefs_from_tool_results=(mode == "full"),
        )
        capture.log(f"synapse.install → {result}", kind="synapse")
        capture.event("install", **result)

        from synapse.bus import Bus
        from synapse.state import StateGraph
        from runtime.router.worker import Router

        bus = Bus(REDIS_URL)
        state = StateGraph(PG_DSN)
        await bus.connect()
        await state.connect()
        router = Router(bus, state, session_id, consumer="v02_auto_router")
        router_task = asyncio.create_task(router.run())
        await asyncio.sleep(0.4)
    else:
        try:
            from synapse.intend import _runtime
            _runtime.clear()
        except Exception:
            pass

    started = time.time()
    summary = await run_orchestrator(
        mode=mode, ant=ant, capture=capture,
        repo_root=repo_root, session_id=session_id,
    )
    elapsed = time.time() - started

    await asyncio.sleep(0.5)
    if router_task is not None:
        router.stop()
        try:
            await asyncio.wait_for(router_task, timeout=2)
        except asyncio.TimeoutError:
            router_task.cancel()

    # End-of-run inspection from PG/bus
    intent_count = belief_count = conflict_count = 0
    if mode != "no_synapse" and state is not None and bus is not None:
        intent_rows = await state.pool.fetch(
            "SELECT id FROM intentions WHERE session_id=$1", session_id,
        )
        belief_rows = await state.pool.fetch(
            "SELECT * FROM beliefs WHERE session_id=$1", session_id,
        )
        intent_count = len(intent_rows)
        belief_count = len(belief_rows)
        agent_rows = await state.pool.fetch(
            "SELECT id FROM agents WHERE session_id=$1", session_id,
        )
        for r in agent_rows:
            entries = await bus.redis.xrange(
                f"synapse:agent:{r['id']}:inbox", count=50,
            )
            for _eid, fields in entries:
                try:
                    env = json.loads(fields["e"])
                    if env["type"] == "CONFLICT":
                        conflict_count += 1
                except Exception:
                    pass

    if bus is not None:
        await bus.close()
    if state is not None:
        await state.close()

    capture.log(
        f"=== {mode} done in {elapsed:.1f}s — turns={summary['turns_completed']} "
        f"files={len(summary['files_written'])} intentions={intent_count} "
        f"conflicts={conflict_count} beliefs={belief_count}",
        kind="system",
    )

    # Export the captures
    export = capture.export(dest_dir)
    return {
        "mode": mode,
        "session_id": session_id,
        "repo_root": repo_root,
        "elapsed_seconds": round(elapsed, 2),
        "turns_completed": summary["turns_completed"],
        "files_written": summary["files_written"],
        "history": summary["history"],
        "intentions_persisted": intent_count,
        "beliefs_persisted": belief_count,
        "conflicts_detected": conflict_count,
        "captures": export,
    }


async def main():
    print("=== v0.2 autonomous observer test ===", flush=True)
    await apply_migrations()
    from anthropic import AsyncAnthropic
    ant = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    dest_dir = "/tmp/v02_auto_captures"
    results: dict[str, dict] = {}

    for mode in ("no_synapse", "observer", "full"):
        results[mode] = await run_one_mode(mode, ant, dest_dir)

    print("\n--- summary ---", flush=True)
    for mode, r in results.items():
        print(
            f"  {mode:13s} turns={r['turns_completed']:2d} "
            f"files={len(r['files_written']):2d} "
            f"intentions={r['intentions_persisted']:3d} "
            f"conflicts={r['conflicts_detected']:2d} "
            f"beliefs={r['beliefs_persisted']:3d} "
            f"elapsed={r['elapsed_seconds']:6.1f}s",
            flush=True,
        )

    return results


if __name__ == "__main__":
    result = asyncio.run(main())
    print("\n--- result.json ---", flush=True)
    # Strip large fields for the printed summary
    trimmed = {}
    for mode, r in result.items():
        c = dict(r)
        c.pop("history", None)
        trimmed[mode] = c
    print(json.dumps(trimmed, indent=2, default=str)[:8000], flush=True)
