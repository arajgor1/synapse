# Synapse skills + agent for Claude Code

Five high-quality skills + one specialist sub-agent that teach Claude Code (and the LLMs running inside it) how to use Synapse coordination from inside a coding session.

## Why 5 not 17

Semantica claims "17 skills" on its IDE integration matrix. We chose to ship five well-crafted skills covering the entire Synapse surface rather than seventeen mechanical wrappers. Each of these answers a question the user actually asks; quality over count.

## Install

```bash
# Option 1: into a project (recommended for team-shared playbooks)
cp -r launch/claude-code-skills/synapse-* /path/to/your/project/.claude/skills/
cp launch/claude-code-agents/synapse-coordinator.md /path/to/your/project/.claude/agents/

# Option 2: globally (recommended for personal use)
cp -r launch/claude-code-skills/synapse-* ~/.claude/skills/
cp launch/claude-code-agents/synapse-coordinator.md ~/.claude/agents/
```

## What's here

| Skill | Triggers when the user says... | Runs |
|---|---|---|
| **synapse-audit** | "audit this trace", "find conflicts in my agent run" | `synapse audit <path>` |
| **synapse-watch** | "watch my agents", "see live coordination", "start the dashboard" | `synapse watch --session <name>` |
| **synapse-intend** | "add Synapse coordination to this code", "claim this scope" | wraps a tool call in `async with synapse.intend(...)` |
| **synapse-resolve-conflict** | "what should I do when `has_conflicts == True`?" | picks a MergePolicy |
| **synapse-explain** | "why did Synapse flag this?" | walks scope-inference + conflict-detection logic |

| Agent | Use when |
|---|---|
| **synapse-coordinator** | The user is investigating, configuring, or debugging multi-agent collisions on shared resources. Knows all 12 framework adapters, all 10 MergePolicies, both operating modes, and all three entry surfaces (SDK, REST, MCP). |

## Verifying

After install:

```bash
# Inside Claude Code, type:
/synapse-watch
# → triggers the skill, runs `synapse watch --session demo`, opens dashboard

# Or invoke the sub-agent for a deeper question:
# Just ask the agent — Claude Code routes coordination questions to synapse-coordinator
```
