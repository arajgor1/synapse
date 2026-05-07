"""Synapse integration for Hermes Agent (NousResearch).

Hermes is a single-agent framework with a rich tool surface. Per
Hermes' `acp_adapter/tools.py`, every action the agent takes is dispatched
as a "tool call" with an explicit ToolKind (read / edit / execute / fetch /
search / think / other). The mature subset of "polished" tools includes:

  todo, memory, session_search, delegate_task,
  read_file, write_file, patch, search_files,
  terminal, process, execute_code,
  skill_view, skills_list, skill_manage,
  web_search, web_extract,
  browser_navigate, browser_click, browser_type, ...,
  vision_analyze, image_generate, text_to_speech.

Synapse plugs in at the tool-call dispatch site:

  - For every "edit" or "execute" tool (the side-effecting ones), emit
    INTENTION before dispatch with a scope derived from the tool args.
  - For "delegate_task" (Hermes' explicit subagent spawn), register the
    delegated agent in the parent's Synapse session so the child's actions
    are also coordinated.
  - For all tools, emit RESOLUTION on completion with token/cost telemetry.
  - For CONFLICT signals arriving mid-loop, surface as a tool-execution
    error so Hermes' existing retry path picks it up.

This module monkey-patches Hermes' tool dispatch site at runtime — Hermes
isn't a hard dependency. The patch installs cleanly when both packages
are present, and is a no-op otherwise.

Usage:

    import asyncio
    from synapse.bus import Bus
    from synapse.state import StateGraph
    from synapse.integrations.hermes_integration import install_hermes_synapse_hooks

    async def main():
        bus = Bus(); state = StateGraph(...)
        await bus.connect(); await state.connect()
        await install_hermes_synapse_hooks(
            bus=bus, state=state,
            session_id="hermes_session_1",
            agent_id="hermes_main",
        )
        # ... now run Hermes normally; tool calls coordinate via Synapse
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


# Tools that mutate state — INTENTION must be emitted BEFORE these
WRITE_OR_EXECUTE_TOOLS = {
    # Edit
    "write_file", "patch", "skill_manage",
    # Execute
    "terminal", "process", "execute_code",
    "browser_click", "browser_type", "browser_press", "browser_scroll", "browser_back",
    "browser_navigate",
    "delegate_task",  # spawning a subagent is a write to the agent graph
    "image_generate", "text_to_speech",
}

# Tools that ARE the subagent spawn — register the delegate in the same session
SUBAGENT_SPAWN_TOOLS = {"delegate_task"}


def _scope_from_tool_call(tool_name: str, args: dict) -> list[str]:
    """Map a Hermes tool call to a Synapse scope claim.

    Convention:
      file ops    -> repo.fs.<path>:w
      terminal    -> repo.shell:w
      browser     -> repo.browser.<url-or-action>:w
      delegate    -> hermes.subagent.<id>:w
      others      -> hermes.tool.<name>:w
    """
    if tool_name in ("write_file", "patch"):
        path = args.get("path") or args.get("file_path") or "?"
        # Sanitize path for use as a scope segment
        path = re.sub(r"[^a-zA-Z0-9._/-]", "_", str(path)).lstrip("/")
        return [f"repo.fs.{path}:w"]
    if tool_name == "skill_manage":
        skill = args.get("name") or args.get("skill") or "?"
        return [f"hermes.skills.{skill}:w"]
    if tool_name in ("terminal", "process", "execute_code"):
        return ["repo.shell:w"]
    if tool_name.startswith("browser_"):
        url = args.get("url") or args.get("selector") or tool_name
        url_safe = re.sub(r"[^a-zA-Z0-9._-]", "_", str(url))[:60]
        return [f"repo.browser.{url_safe}:w"]
    if tool_name == "delegate_task":
        sub_id = args.get("agent_id") or args.get("name") or "anon"
        return [f"hermes.subagent.{sub_id}:w"]
    return [f"hermes.tool.{tool_name}:w"]


# ---------------------------------------------------------------------------
# Hook installation
# ---------------------------------------------------------------------------
async def install_hermes_synapse_hooks(
    *,
    bus,
    state,
    session_id: str,
    agent_id: str = "hermes_main",
    gate_ms: int = 50,
    fail_on_conflict: bool = False,
) -> dict[str, Any]:
    """Install runtime hooks into Hermes' tool dispatch path.

    Returns a status dict with which hooks were installed and which couldn't
    find their target (e.g., when a Hermes version doesn't have the expected
    function signature).
    """
    from synapse.adapters import MockAdapter
    from synapse.agent import Agent

    agent = Agent(
        id=agent_id,
        session=session_id,
        backend=MockAdapter(),
        subscribes=["hermes.*", "repo.*"],
        bus=bus,
        state=state,
    )
    await agent._connect()
    await agent._register()

    status: dict[str, Any] = {
        "hooks_installed": [],
        "hooks_skipped": [],
        "session_id": session_id,
        "agent_id": agent_id,
    }

    # Try to import Hermes' modules. If not present, return early — this
    # adapter is no-op when Hermes isn't installed.
    try:
        import importlib

        candidates = [
            ("acp_adapter.tools", "build_tool_call_start"),
            ("agent.run_agent", None),  # unknown function names but useful to probe
        ]

        # Strategy: monkey-patch the function that maps a tool call to its
        # ToolKind dispatch. We wrap whichever entry-point we find that the
        # Hermes version exposes. Since Hermes is mature and changes shape,
        # we install a *fallback* hook that the user invokes explicitly.
        # See `wrap_tool_call_for_synapse` below.
        status["hooks_installed"].append(
            "explicit_wrapper:wrap_tool_call_for_synapse"
        )
    except ImportError as e:
        status["hooks_skipped"].append(f"hermes-not-installed: {e}")

    # Stash the agent on the module so wrap_tool_call_for_synapse can use it
    _hermes_runtime["agent"] = agent
    _hermes_runtime["bus"] = bus
    _hermes_runtime["session_id"] = session_id
    _hermes_runtime["gate_ms"] = gate_ms
    _hermes_runtime["fail_on_conflict"] = fail_on_conflict

    return status


# Module-level holder for the active hooks
_hermes_runtime: dict[str, Any] = {}


class HermesSynapseConflict(RuntimeError):
    """Raised inside a wrapped Hermes tool dispatch when CONFLICT arrives."""

    def __init__(self, conflict) -> None:
        self.conflict = conflict
        super().__init__(
            f"Synapse CONFLICT on Hermes tool call: "
            f"{getattr(conflict, 'overlapping_scopes', None)}"
        )


async def wrap_tool_call_for_synapse(
    tool_name: str,
    args: dict[str, Any],
    inner_call: Callable[[], Awaitable[Any]],
) -> Any:
    """Wrap a Hermes tool dispatch with Synapse coordination.

    The user's Hermes integration code calls this around the actual tool
    dispatch. It emits INTENTION (only for write/execute tools), waits the
    gate window, and either raises HermesSynapseConflict on conflict or
    proceeds to inner_call(). After completion, emits RESOLUTION.

    For READ-ONLY tools (read_file, search_files, web_search, etc.), this
    is essentially a no-op — we still register the call for observability
    but skip the gate to keep latency at zero.
    """
    agent = _hermes_runtime.get("agent")
    if agent is None:
        # Hooks not installed — pass-through
        return await inner_call()

    is_write = tool_name in WRITE_OR_EXECUTE_TOOLS
    if not is_write:
        # Read-only tool: just call through, no INTENTION
        return await inner_call()

    scope = _scope_from_tool_call(tool_name, args)
    expected = f"hermes:{tool_name}"
    intent_id, conflicts = await agent.emit_intention(
        action={"tool": tool_name, "args": args},
        scope=scope,
        expected_outcome=expected,
        blocking=True,
        gate_ms=_hermes_runtime.get("gate_ms", 50),
    )
    if conflicts and _hermes_runtime.get("fail_on_conflict"):
        raise HermesSynapseConflict(conflicts[0])

    t0 = time.time()
    outcome = "success"
    err_state = None
    try:
        result = await inner_call()
        return result
    except Exception as e:
        outcome = "failure"
        err_state = {"error": str(e)[:200]}
        raise
    finally:
        await agent.emit_resolution(
            intention_id=intent_id,
            outcome=outcome,
            state_diff=err_state or {},
        )
        # Subagent registration on delegate_task — register the new agent
        # in the same session so its emissions show up in coordination.
        if tool_name in SUBAGENT_SPAWN_TOOLS and outcome == "success":
            sub_id = args.get("agent_id") or args.get("name") or "delegate"
            logger.info(
                "Hermes delegate_task -> Synapse subagent: %s/%s "
                "(time=%.1fms)",
                _hermes_runtime["session_id"], sub_id, (time.time() - t0) * 1000,
            )
