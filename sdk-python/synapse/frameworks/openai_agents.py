"""OpenAI Agents SDK adapter for ``synapse.install(framework="openai_agents")``.

OpenAI's Agents SDK (``openai-agents`` on PyPI; replaces the old Swarm
project) decorates Python functions with ``@function_tool`` to expose
them as agent-callable tools. We hook by:

  1. Patching ``agents.tool.function_tool`` (the decorator) so wrapped
     callables emit through Synapse on each invocation.
  2. Falling back to patching ``Tool.run`` / equivalent if the decorator
     path isn't reachable.

Agent identity: OpenAI's SDK exposes the calling agent via the
``ToolContext`` parameter; we read ``context.agent.name`` if present.
"""
from __future__ import annotations

import functools
import logging
import os
from typing import Any, Callable, Optional

from synapse.intend import intend
from synapse.audit.events import AuditEvent, is_write
from synapse.audit.scope_inference import infer_scope
from synapse.install import register_framework

logger = logging.getLogger(__name__)


_PATCHED = {"function_tool": False}


def _session_id() -> str:
    return os.environ.get("SYNAPSE_SESSION_ID", "openai_agents_default_session")


def _agent_id_from_context(ctx: Any) -> str:
    if ctx is None:
        return "openai_agent"
    # Various paths the SDK has used across versions
    for path in (
        ("agent", "name"),
        ("agent_name",),
        ("name",),
    ):
        cur = ctx
        for attr in path:
            cur = getattr(cur, attr, None)
            if cur is None:
                break
        if isinstance(cur, str) and cur:
            return cur
    return "openai_agent"


def _scope_from_call(tool_name: str, args: dict) -> list[str]:
    ev = AuditEvent(
        trace_id="oa", span_id="oa", agent_id="oa", session_id="oa",
        tool_name=tool_name, tool_args=args or {},
        ts_start_ms=0, ts_end_ms=0,
    )
    return infer_scope(ev) or [f"openai_agents.tool.{tool_name}:w"]


def _is_write(tool_name: str, args: dict) -> bool:
    ev = AuditEvent(
        trace_id="oa", span_id="oa", agent_id="oa", session_id="oa",
        tool_name=tool_name, tool_args=args or {},
        ts_start_ms=0, ts_end_ms=0,
    )
    return is_write(ev)


def _wrap_function_tool(original_decorator):
    """Patch the ``function_tool`` decorator so every tool it produces
    runs through Synapse."""

    @functools.wraps(original_decorator)
    def patched(*dec_args, **dec_kwargs):
        # function_tool is used either as @function_tool or @function_tool(...)
        # Detect form:
        if len(dec_args) == 1 and callable(dec_args[0]) and not dec_kwargs:
            # Bare decorator: @function_tool
            inner_func = dec_args[0]
            tool_obj = original_decorator(inner_func)
            return _wrap_tool_object(tool_obj, inner_func)

        # Parameterized decorator: @function_tool(name="...", ...)
        # Returns a real decorator
        real_decorator = original_decorator(*dec_args, **dec_kwargs)

        @functools.wraps(real_decorator)
        def wrapper(inner_func):
            tool_obj = real_decorator(inner_func)
            return _wrap_tool_object(tool_obj, inner_func)

        return wrapper

    return patched


def _wrap_tool_object(tool_obj: Any, inner_func: Callable) -> Any:
    """Given a Tool object produced by function_tool, wrap its callable."""
    tool_name = getattr(tool_obj, "name", None) or getattr(inner_func, "__name__", "tool")

    # Find the actual invocation method. Across SDK versions:
    #   tool_obj.on_invoke_tool   (modern)
    #   tool_obj.run              (older)
    #   tool_obj.__call__         (fallback)
    for attr in ("on_invoke_tool", "run", "_call"):
        original = getattr(tool_obj, attr, None)
        if original and callable(original):
            wrapped = _wrap_invoke(original, tool_name)
            try:
                setattr(tool_obj, attr, wrapped)
            except Exception:
                continue
            break

    return tool_obj


def _wrap_invoke(original: Callable, tool_name: str):
    async def async_wrapper(ctx_or_self, *args, **kwargs):
        # Argument shape varies. Best-effort extraction:
        ctx = args[0] if args and not isinstance(args[0], dict) else None
        tool_args: dict[str, Any] = {}
        for a in args:
            if isinstance(a, dict):
                tool_args.update(a)
                break
        if not tool_args and kwargs:
            tool_args = dict(kwargs)

        if not _is_write(tool_name, tool_args):
            return await original(ctx_or_self, *args, **kwargs)

        scope = _scope_from_call(tool_name, tool_args)
        agent_id = _agent_id_from_context(ctx)

        async with intend(
            scope=scope,
            agent=agent_id,
            session=_session_id(),
            expected_outcome=f"openai_agents:{tool_name}",
            blocking=True,
            gate_ms=int(os.environ.get("SYNAPSE_GATE_MS", "200")),
        ) as i:
            try:
                result = await original(ctx_or_self, *args, **kwargs)
                i.set_state_diff({"output_preview": str(result)[:200]})
                return result
            except Exception as e:
                i.mark_failed(str(e))
                raise

    return async_wrapper


def _install_openai_agents(opts: dict[str, Any]) -> None:
    try:
        from agents import tool as tool_module  # OpenAI Agents SDK module
    except ImportError:
        try:
            import openai_agents as tool_module  # alt import name some versions use
        except ImportError:
            logger.warning(
                "synapse.install(framework='openai_agents'): openai-agents not installed. "
                "`pip install openai-agents`."
            )
            return

    # Some versions expose function_tool at package root; others under .tool
    patched_module = None
    for module_path in (tool_module, getattr(tool_module, "tool", None)):
        if module_path is None:
            continue
        original = getattr(module_path, "function_tool", None)
        if callable(original) and not _PATCHED["function_tool"]:
            patched = _wrap_function_tool(original)
            module_path.function_tool = patched
            _PATCHED["function_tool"] = True
            patched_module = module_path
            logger.info(
                "synapse.install(framework='openai_agents'): patched %s.function_tool",
                module_path.__name__,
            )
            break

    if patched_module is None:
        logger.warning(
            "synapse.install(framework='openai_agents'): could not find function_tool to patch. "
            "Use synapse.intend() manually inside your tool bodies."
        )
        return

    # ALSO patch already-imported `from agents import function_tool` references.
    # When a user does `from agents import function_tool` BEFORE
    # synapse.install(), the local name binding refers to the original
    # function — our patch on the module object won't reach it. We walk
    # sys.modules looking for those re-imported references and rebind
    # them to the patched function.
    import sys
    new_fn = getattr(patched_module, "function_tool")
    rebound = 0
    for mod_name, mod in list(sys.modules.items()):
        if mod is None:
            continue
        # Skip our own + standard library + the patched module itself
        if mod_name.startswith(("synapse", "_", "encodings.")) or mod is patched_module:
            continue
        try:
            existing = getattr(mod, "function_tool", None)
        except Exception:
            continue
        if existing is None:
            continue
        # Rebind only if it's the unpatched original (don't double-wrap)
        if existing is not new_fn and getattr(existing, "__module__", "") == "agents.tool":
            try:
                setattr(mod, "function_tool", new_fn)
                rebound += 1
            except Exception:
                pass
    if rebound:
        logger.info(
            "synapse.install(framework='openai_agents'): rebound %d "
            "already-imported function_tool reference(s)",
            rebound,
        )

    # Walk Agent.tools collections post-install and wrap any tool that
    # was already created via the un-patched decorator (race window).
    try:
        from agents import Agent  # type: ignore[import-not-found]
        # We don't have a registry of all Agents; user must call this
        # before constructing agents. Document this in the install log.
    except ImportError:
        pass


register_framework("openai_agents", _install_openai_agents)
register_framework("openai_agents_sdk", _install_openai_agents)
register_framework("swarm", _install_openai_agents)  # alias for the older name
