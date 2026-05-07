# Framework integration docs (fetched from sandboxes)

```
=== Paperclip adapter-plugin.md ===
Cloning into 'paperclip'...

--- adapter-plugin.md ---
- Created branch: feat/external-adapter-phase1

   I started phase 1 in the most merge-friendly way I could: small central changes, reusing existing registry patterns instead of inventing a whole new plugin system up front.

   What I changed

   1. Server adapter registry is now mutable
   Files:
  - server/src/adapters/registry.ts
  - server/src/adapters/index.ts

   Added:
  - registerServerAdapter(adapter)
  - unregisterServerAdapter(type)
  - requireServerAdapter(type)

   Kept the existing built-in registry shape, but changed initialization so built-ins are registered into a mutable map on startup.

   Why this is merge-friendly:
  - existing built-in adapter definitions stay where they already are
  - existing lookup helpers still exist
  - no big architectural rewrite yet

   1. Runtime adapter validation moved to server routes
   File:
  - server/src/routes/agents.ts

   Added:
  - assertKnownAdapterType(...)

   Used it in:
  - /companies/:companyId/adapters/:type/models
  - /companies/:companyId/adapters/:type/detect-model
  - /companies/:companyId/adapters/:type/test-environment
  - POST /companies/:companyId/agents
  - POST /companies/:companyId/agent-hires
  - PATCH /agents/:id when adapterType is touched

   Why:
  - shared schemas can now allow external adapter strings
  - server becomes the real source of truth for “is this adapter actually registered?”

   1. Shared adapterType validation is now open-ended for inputs
   Files:
  - packages/shared/src/adapter-type.ts
  - packages/shared/src/validators/agent.ts
  - packages/shared/src/validators/access.ts
  - packages/shared/src/index.ts

   Changed input validation from hardcoded z.enum(AGENT_ADAPTER_TYPES) to:
  - agentAdapterTypeSchema
  - optionalAgentAdapterTypeSchema

   These accept any non-empty string.

   Important:
  - I did not remove AGENT_ADAPTER_TYPES from constants
  - I did not change the built-in type unions yet
  - this keeps the change minimal and limits blast radius

   So:
  - input payloads can carry external adapter types
  - actual acceptance still depends on server registry validation

   1. UI adapter registry is now mutable too
   Files:
  - ui/src/adapters/registry.ts
  - ui/src/adapters/index.ts

   Added:
  - registerUIAdapter(adapter)
  - unregisterUIAdapter(type)
  - findUIAdapter(type)

   Built-ins are still registered from the same file, same pattern as server.

   1. Began switching UI adapter lists toward the registry
   Files:
  - ui/src/adapters/metadata.ts
  - ui/src/components/AgentConfigForm.tsx
  - ui/src/pages/NewAgent.tsx

   Changed:
  - AgentConfigForm adapter list now comes from registered UI adapters via metadata helper
  - NewAgent supported adapter set now derives from listUIAdapters()

   Why:
  - phase 1 should start reducing hardcoded UI lists
  - but without rewriting every page at once

   1. Tests added first, then implementation
   New tests:
  - server/src/__tests__/adapter-registry.test.ts
  - server/src/__tests__/agent-adapter-validation-routes.test.ts
  - ui/src/adapters/registry.test.ts
  - packages/shared/src/adapter-types.test.ts

   Small test mock fix:
  - server/src/__tests__/agent-skills-routes.test.ts

   Current status

   The branch is created and the phase-1 code is started.

   I also followed TDD in spirit:
  - wrote failing tests first for missing register/unregister APIs
  - then implemented the registry changes

   What is not finished yet

   I have not finished the green/stabilization pass yet.

   I still need to:
  - run the targeted tests again after the implementation changes
  - fix any TS / mocking fallout
  - decide how far to take phase-1 UI wiring in this branch before stopping

   Also, I intentionally did not yet touch the bigger hardcoded surfaces like:
  - NewAgentDialog
  - OnboardingWizard
  - InviteLanding
  - duplicated adapterLabels maps
  - plugin manifest / plugin loader adapter contributions

   That is deliberate.
   For merge safety, I started with the smallest useful seam:
  - dynamic server registry
  - dynamic UI registry
  - runtime validation based on registry
  - first couple of UI consumers

   One note
   There was already an unrelated dirty change in:
  - server/scripts/dev-watch.ts

   I left that alone and did not make phase-1 changes there.

   Recommended next move
   I should keep going on this same branch and do the stabilization pass:
   1. rerun server/ui/shared targeted tests
   2. fix failures
   3. run typechecks
   4. then extend the same registry-driven approach to the next safest UI surfaces

--- AGENTS.md (top 80) ---
# AGENTS.md

Guidance for human and AI contributors working in this repository.

## 1. Purpose

Paperclip is a control plane for AI-agent companies.
The current implementation target is V1 and is defined in `doc/SPEC-implementation.md`.

## 2. Read This First

Before making changes, read in this order:

1. `doc/GOAL.md`
2. `doc/PRODUCT.md`
3. `doc/SPEC-implementation.md`
4. `doc/DEVELOPING.md`
5. `doc/DATABASE.md`

`doc/SPEC.md` is long-horizon product context.
`doc/SPEC-implementation.md` is the concrete V1 build contract.

## 3. Repo Map

- `server/`: Express REST API and orchestration services
- `ui/`: React + Vite board UI
- `packages/db/`: Drizzle schema, migrations, DB clients
- `packages/shared/`: shared types, constants, validators, API path constants
- `packages/adapters/`: agent adapter implementations (Claude, Codex, Cursor, etc.)
- `packages/adapter-utils/`: shared adapter utilities
- `packages/plugins/`: plugin system packages
- `doc/`: operational and product docs

## 4. Dev Setup (Auto DB)

Use embedded PGlite in dev by leaving `DATABASE_URL` unset.

```sh
pnpm install
pnpm dev
```

This starts:

- API: `http://localhost:3100`
- UI: `http://localhost:3100` (served by API server in dev middleware mode)

Quick checks:

```sh
curl http://localhost:3100/api/health
curl http://localhost:3100/api/companies
```

Reset local dev DB:

```sh
rm -rf data/pglite
pnpm dev
```

## 5. Core Engineering Rules

1. Keep changes company-scoped.
Every domain entity should be scoped to a company and company boundaries must be enforced in routes/services.

2. Keep contracts synchronized.
If you change schema/API behavior, update all impacted layers:
- `packages/db` schema and exports
- `packages/shared` types/constants/validators
- `server` routes/services
- `ui` API clients and pages

3. Preserve control-plane invariants.
- Single-assignee task model
- Atomic issue checkout semantics
- Approval gates for governed actions
- Budget hard-stop auto-pause behavior
- Activity logging for mutating actions


--- packages/ contents ---
total 0
drwxr-xr-x 1 root root 160 May  7 15:50 .
drwxr-xr-x 1 root root 780 May  7 15:50 ..
drwxr-xr-x 1 root root 120 May  7 15:50 adapter-utils
drwxr-xr-x 1 root root 200 May  7 15:50 adapters
drwxr-xr-x 1 root root 180 May  7 15:50 db
drwxr-xr-x 1 root root 140 May  7 15:50 mcp-server
drwxr-xr-x 1 root root 140 May  7 15:50 plugins
drwxr-xr-x 1 root root 140 May  7 15:50 shared

--- README highlights (multi-agent + adapter sections) ---
35:It looks like a task manager — but under the hood it has org charts, budgets, governance, goal alignment, and agent coordination.
73:- ✅ You **coordinate many different agents** (OpenClaw, Codex, Claude, Cursor) toward a common goal
137:| ❌ Folders of agent configs are disorganized and you're re-inventing task management, communication, and coordination between agents. | ✅ Paperclip gives you org charts, ticketing, delegation, and governance out of the box — so you run a company, not a pile of scripts. |
201:**Org Chart & Agents** — Agents have roles, titles, reporting lines, permissions, and budgets. Adapter examples match the diagram: Claude Code, Codex, CLI agents such as Cursor/Gemini/bash, HTTP/webhook bots such as OpenClaw, and external adapter plugins. If it can receive a heartbeat, it's hired.
213:**Heartbeat Execution** — DB-backed wakeup queue with coalescing, budget checks, workspace resolution, secret injection, skill loading, and adapter invocation. Runs produce structured logs, cost events, session state, and audit trails. Recovery handles orphaned runs automatically.
244:**Plugins** — Instance-wide plugin system with out-of-process workers, capability-gated host services, job scheduling, tool exposure, and UI contributions. Extend Paperclip without forking it.
329:Agent orchestration has subtleties in how you coordinate who has work checked out, how to maintain sessions, monitoring costs, establishing governance - Paperclip does this for you.
334:By default, agents run on scheduled heartbeats and event-based triggers (task assignment, @-mentions). You can also hook in continuous agents like OpenClaw. You bring your agent and Paperclip coordinates.

--- skills/openclaw-* (the existing OpenClaw integration) ---
paperclip/doc/assets/logos/openclaw.svg
paperclip/docs/guides/openclaw-docker-setup.md
paperclip/scripts/smoke/openclaw-docker-ui.sh
paperclip/scripts/smoke/openclaw-gateway-e2e.sh
paperclip/scripts/smoke/openclaw-join.sh
paperclip/scripts/smoke/openclaw-sse-standalone.sh
paperclip/server/src/__tests__/openclaw-gateway-adapter.test.ts
paperclip/server/src/__tests__/openclaw-invite-prompt-route.test.ts

=== Hermes agent: tool-call dispatch site ===
Cloning into 'hermes-agent'...

--- agent/__init__.py (full) ---
"""Agent internals -- extracted modules from run_agent.py.

These modules contain pure utility functions and self-contained classes
that were previously embedded in the 3,600-line run_agent.py. Extracting
them makes run_agent.py focused on the AIAgent orchestrator class.
"""

--- acp_adapter/tools.py first 120 lines ---
"""ACP tool-call helpers for mapping hermes tools to ACP ToolKind and building content."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

import acp
from acp.schema import (
    ToolCallLocation,
    ToolCallStart,
    ToolCallProgress,
    ToolKind,
)

# ---------------------------------------------------------------------------
# Map hermes tool names -> ACP ToolKind
# ---------------------------------------------------------------------------

TOOL_KIND_MAP: Dict[str, ToolKind] = {
    # File operations
    "read_file": "read",
    "write_file": "edit",
    "patch": "edit",
    "search_files": "search",
    # Terminal / execution
    "terminal": "execute",
    "process": "execute",
    "execute_code": "execute",
    # Session/meta tools
    "todo": "other",
    "skill_view": "read",
    "skills_list": "read",
    "skill_manage": "edit",
    # Web / fetch
    "web_search": "fetch",
    "web_extract": "fetch",
    # Browser
    "browser_navigate": "fetch",
    "browser_click": "execute",
    "browser_type": "execute",
    "browser_snapshot": "read",
    "browser_vision": "read",
    "browser_scroll": "execute",
    "browser_press": "execute",
    "browser_back": "execute",
    "browser_get_images": "read",
    # Agent internals
    "delegate_task": "execute",
    "vision_analyze": "read",
    "image_generate": "execute",
    "text_to_speech": "execute",
    # Thinking / meta
    "_thinking": "think",
}


_POLISHED_TOOLS = {
    # Core operator loop
    "todo", "memory", "session_search", "delegate_task",
    # Files / execution
    "read_file", "write_file", "patch", "search_files", "terminal", "process", "execute_code",
    # Skills / web / browser / media
    "skill_view", "skills_list", "skill_manage", "web_search", "web_extract",
    "browser_navigate", "browser_click", "browser_type", "browser_press", "browser_scroll",
    "browser_back", "browser_snapshot", "browser_console", "browser_get_images", "browser_vision",
    "vision_analyze", "image_generate", "text_to_speech",
    # Schedulers / platform integrations
    "cronjob", "send_message", "clarify", "discord", "discord_admin",
    "ha_list_entities", "ha_get_state", "ha_list_services", "ha_call_service",
    "feishu_doc_read", "feishu_drive_list_comments", "feishu_drive_list_comment_replies",
    "feishu_drive_reply_comment", "feishu_drive_add_comment",
    "kanban_create", "kanban_show", "kanban_comment", "kanban_complete",
    "kanban_block", "kanban_link", "kanban_heartbeat",
    "yb_query_group_info", "yb_query_group_members", "yb_search_sticker",
    "yb_send_dm", "yb_send_sticker", "mixture_of_agents",
}


def get_tool_kind(tool_name: str) -> ToolKind:
    """Return the ACP ToolKind for a hermes tool, defaulting to 'other'."""
    return TOOL_KIND_MAP.get(tool_name, "other")


def make_tool_call_id() -> str:
    """Generate a unique tool call ID."""
    return f"tc-{uuid.uuid4().hex[:12]}"


def build_tool_title(tool_name: str, args: Dict[str, Any]) -> str:
    """Build a human-readable title for a tool call."""
    if tool_name == "terminal":
        cmd = args.get("command", "")
        if len(cmd) > 80:
            cmd = cmd[:77] + "..."
        return f"terminal: {cmd}"
    if tool_name == "read_file":
        return f"read: {args.get('path', '?')}"
    if tool_name == "write_file":
        return f"write: {args.get('path', '?')}"
    if tool_name == "patch":
        mode = args.get("mode", "replace")
        path = args.get("path", "?")
        return f"patch ({mode}): {path}"
    if tool_name == "search_files":
        return f"search: {args.get('pattern', '?')}"
    if tool_name == "web_search":
        return f"web search: {args.get('query', '?')}"
    if tool_name == "web_extract":
        urls = args.get("urls", [])
        if urls:
            return f"extract: {urls[0]}" + (f" (+{len(urls)-1})" if len(urls) > 1 else "")
        return "web extract"
    if tool_name == "process":
        action = str(args.get("action") or "").strip() or "manage"
        sid = str(args.get("session_id") or "").strip()
        return f"process {action}: {sid}" if sid else f"process {action}"
    if tool_name == "delegate_task":
        tasks = args.get("tasks")

--- Search for the tool-execution function ---

=== OpenClaw extension/plugin pattern ===
Cloning into 'openclaw-sparse'...
fatal: 'README.md' is not a directory; to treat it as a directory anyway, rerun with --skip-checks

--- README highlights ---
# 🦞 OpenClaw — Personal AI Assistant

<p align="center">
    <picture>
        <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/openclaw/openclaw/main/docs/assets/openclaw-logo-text-dark.svg">
        <img src="https://raw.githubusercontent.com/openclaw/openclaw/main/docs/assets/openclaw-logo-text.svg" alt="OpenClaw" width="500">
    </picture>
</p>

<p align="center">
  <strong>EXFOLIATE! EXFOLIATE!</strong>
</p>

<p align="center">
  <a href="https://github.com/openclaw/openclaw/actions/workflows/ci.yml?branch=main"><img src="https://img.shields.io/github/actions/workflow/status/openclaw/openclaw/ci.yml?branch=main&style=for-the-badge" alt="CI status"></a>
  <a href="https://github.com/openclaw/openclaw/releases"><img src="https://img.shields.io/github/v/release/openclaw/openclaw?include_prereleases&style=for-the-badge" alt="GitHub release"></a>
  <a href="https://discord.gg/clawd"><img src="https://img.shields.io/discord/1456350064065904867?label=Discord&logo=discord&logoColor=white&color=5865F2&style=for-the-badge" alt="Discord"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="MIT License"></a>
</p>

**OpenClaw** is a _personal AI assistant_ you run on your own devices.
It answers you on the channels you already use. It can speak and listen on macOS/iOS/Android, and can render a live Canvas you control. The Gateway is just the control plane — the product is the assistant.

If you want a personal, single-user assistant that feels local, fast, and always-on, this is it.

Supported channels include: WhatsApp, Telegram, Slack, Discord, Google Chat, Signal, iMessage, BlueBubbles, IRC, Microsoft Teams, Matrix, Feishu, LINE, Mattermost, Nextcloud Talk, Nostr, Synology Chat, Tlon, Twitch, Zalo, Zalo Personal, WeChat, QQ, WebChat.

[Website](https://openclaw.ai) · [Docs](https://docs.openclaw.ai) · [Vision](VISION.md) · [DeepWiki](https://deepwiki.com/openclaw/openclaw) · [Getting Started](https://docs.openclaw.ai/start/getting-started) · [Updating](https://docs.openclaw.ai/install/updating) · [Showcase](https://docs.openclaw.ai/start/showcase) · [FAQ](https://docs.openclaw.ai/help/faq) · [Onboarding](https://docs.openclaw.ai/start/wizard) · [Nix](https://github.com/openclaw/nix-openclaw) · [Docker](https://docs.openclaw.ai/install/docker) · [Discord](https://discord.gg/clawd)

New install? Start here: [Getting started](https://docs.openclaw.ai/start/getting-started)

Preferred setup: run `openclaw onboard` in your terminal.
OpenClaw Onboard guides you step by step through setting up the gateway, workspace, channels, and skills. It is the recommended CLI setup path and works on **macOS, Linux, and Windows (via WSL2; strongly recommended)**.
Works with npm, pnpm, or bun.

## Sponsors

<table>
  <tr>
    <td align="center" width="16.66%">
      <a href="https://openai.com/">
        <picture>
          <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/openclaw/openclaw/main/docs/assets/sponsors/openai-light.svg">
          <img src="https://raw.githubusercontent.com/openclaw/openclaw/main/docs/assets/sponsors/openai.svg" alt="OpenAI" height="28">
        </picture>
      </a>
    </td>
    <td align="center" width="16.66%">
      <a href="https://github.com/">
        <picture>
          <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/openclaw/openclaw/main/docs/assets/sponsors/github-light.svg">
          <img src="https://raw.githubusercontent.com/openclaw/openclaw/main/docs/assets/sponsors/github.svg" alt="GitHub" height="28">
        </picture>
      </a>
    </td>
    <td align="center" width="16.66%">
      <a href="https://www.nvidia.com/">
        <picture>
          <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/openclaw/openclaw/main/docs/assets/sponsors/nvidia.svg">
          <img src="https://raw.githubusercontent.com/openclaw/openclaw/main/docs/assets/sponsors/nvidia-dark.svg" alt="NVIDIA" height="28">
        </picture>
      </a>
    </td>
    <td align="center" width="16.66%">
      <a href="https://vercel.com/">
        <picture>
          <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/openclaw/openclaw/main/docs/assets/sponsors/vercel-light.svg">
          <img src="https://raw.githubusercontent.com/openclaw/openclaw/main/docs/assets/sponsors/vercel.svg" alt="Vercel" height="24">
        </picture>
      </a>
    </td>
    <td align="center" width="16.66%">
      <a href="https://blacksmith.sh/">
        <picture>
          <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/openclaw/openclaw/main/docs/assets/sponsors/blacksmith-light.svg">
          <img src="https://raw.githubusercontent.com/openclaw/openclaw/main/docs/assets/sponsors/blacksmith.svg" alt="Blacksmith" height="28">
        </picture>
      </a>
    </td>
    <td align="center" width="16.66%">

--- extensions/browser/plugin-registration.ts (the canonical plugin example) ---

--- SOUL.md template doc ---

--- Plugin registration API surface (grep across extensions) ---

```
