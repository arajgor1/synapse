# CrewAI marketing crew — with and without Synapse

A 60-second demo: a 3-agent CrewAI marketing crew (**Researcher → Writer →
Editor**) that all touch the same `drafts/` directory. Without Synapse, the
Editor silently overwrites the Writer's revision. With Synapse, the
collision is caught and surfaced live in your browser.

## What this proves

- Synapse runs **autonomously** in a real CrewAI workflow.
- **Zero infra needed** — no Redis, no Postgres, no env vars.
- The auto-spawned in-process router detects the file collision and
  delivers a CONFLICT envelope to the second writer's inbox during its
  gate window.
- The live `synapse watch` dashboard shows the conflict in real time.

## Run it (60 seconds)

```bash
# 1. Install
pip install synapse-protocol crewai

# 2. Start the live dashboard (opens a browser tab)
synapse watch --session crew_demo

# 3. In a SECOND terminal, run the crew
python crew.py
```

You'll see the dashboard tick up to:

- **3 events** (one per agent's tool call)
- **1 conflict** (Editor + Writer both writing `drafts/post.md`)
- **3 agents** (researcher, writer, editor)

## What's inside

- `crew.py` — the 3-agent CrewAI crew. Each agent calls a `write_draft`
  tool. Without Synapse, the Editor's call would silently clobber the
  Writer's. With Synapse (it's already wired in), the second writer
  sees `IntentionHandle.has_conflicts == True` and logs a clear
  rationale instead of overwriting.
- `crew_no_synapse.py` — the same flow with Synapse removed. Run this
  to confirm the Editor *would* have silently overwritten without
  coordination.
- `tools.py` — the shared `write_draft` and `read_draft` tools. Plain
  Python — Synapse needs no tool changes.

## Without Synapse (control)

```bash
python crew_no_synapse.py
# → "Editor wrote drafts/post.md (123 bytes)"
# → "Writer wrote drafts/post.md (98 bytes)"
# → file contains the LATER write — the earlier one is silently lost.
```

## With Synapse

```bash
synapse watch --session crew_demo &
python crew.py
# → "Writer claimed drafts/post.md"
# → "Editor: SYNAPSE CONFLICT — Writer is editing drafts/post.md
#         (started 0.4s ago). Pausing edit, will retry."
# → file contains BOTH writes (Editor pivoted to a different file).
```

The live dashboard at http://localhost:8766/ shows every claim and the
conflict in real time.

## The shape of the bug Synapse catches

This is the canonical multi-agent collision pattern: two agents with
overlapping responsibilities both touch the same shared resource on
the same turn. In real CrewAI deployments this looks like:

- Researcher pushes notes → Writer drafts → Editor revises, but
  nondeterministic timing means Editor sometimes runs before Writer
  finishes.
- Two parallel CrewAI tasks both scheduled with `async_execution=True`
  on the same output file.
- A `kickoff_for_each` sweep where individual agents independently
  decide to update the same artifact.

Synapse's contribution: every tool call emits an INTENTION + scope
claim. Overlapping scopes on the same session trigger a CONFLICT
envelope back to the offending agent during the pre-execution gate
window. The agent's code can then pivot, wait, or escalate — instead
of silently writing through.
