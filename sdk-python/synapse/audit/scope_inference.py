"""Rules-based scope inference for AuditEvents.

Given a normalized tool call, return a list of Synapse scope strings
(e.g. ``["repo.fs.models/user.py:w"]``) that represent what the call
will mutate. Scope vocabulary is the same as the live runtime so the
audit's conflict detection produces the same results as a live router.

Rules ship for the most common tool families. Users can register custom
rules via ``register_scope_rule``. An optional LLM-fallback path exists
for unknown tool names but is a no-op unless ``synapse.set_llm()`` has
been called (BYO-LLM principle).
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from .events import AuditEvent

# A scope rule looks at a tool call and returns either a list of scope
# strings (handled) or None (pass to next rule).
ScopeRule = Callable[[AuditEvent], Optional[list[str]]]


_RULES: list[ScopeRule] = []


def register_scope_rule(rule: ScopeRule) -> None:
    """Register a custom scope-inference rule. Rules are tried in order
    of registration; first match wins. Custom rules run BEFORE the
    built-in defaults so users can override behavior per tool.
    """
    _RULES.insert(0, rule)


def _sanitize_path(p: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._/-]", "_", p).lstrip("/")


def _filesystem_rule(ev: AuditEvent) -> Optional[list[str]]:
    """File-write tools across most agent frameworks."""
    name = ev.tool_name.lower()
    fs_writes = {
        "write_file", "write", "edit_file", "edit", "patch", "patch_file",
        "create_file", "delete_file", "fs.write", "fs.edit", "fs.delete",
        "files_create", "files_update", "str_replace_editor",
        "filesystem.write", "filesystem.edit",
    }
    if name in fs_writes or any(name.endswith(suf) for suf in (".write", ".edit", ".patch")):
        path = (
            ev.tool_args.get("path")
            or ev.tool_args.get("file_path")
            or ev.tool_args.get("filename")
            or ev.tool_args.get("filepath")
        )
        if path:
            return [f"repo.fs.{_sanitize_path(str(path))}:w"]
        return [f"repo.fs.unknown:w"]
    return None


def _shell_rule(ev: AuditEvent) -> Optional[list[str]]:
    """Shell / terminal / subprocess tools."""
    name = ev.tool_name.lower()
    shell_tools = {
        "terminal", "shell", "bash", "sh", "subprocess", "execute_code",
        "run_command", "exec", "run", "process",
    }
    if name in shell_tools:
        return ["repo.shell:w"]
    return None


def _http_rule(ev: AuditEvent) -> Optional[list[str]]:
    """HTTP write methods (POST/PUT/PATCH/DELETE) hit a resource scope."""
    name = ev.tool_name.lower()
    if name in {"http_request", "fetch", "request"} or name.startswith("http."):
        method = str(ev.tool_args.get("method", "GET")).upper()
        url = str(ev.tool_args.get("url", "")) or str(ev.tool_args.get("endpoint", ""))
        if method in {"POST", "PUT", "PATCH", "DELETE"} and url:
            host = re.sub(r"^https?://", "", url).split("/")[0] or "unknown"
            host_safe = re.sub(r"[^a-zA-Z0-9.-]", "_", host)
            return [f"http.{host_safe}.{method.lower()}:w"]
    return None


def _db_rule(ev: AuditEvent) -> Optional[list[str]]:
    """Database write tools."""
    name = ev.tool_name.lower()
    db_writes = {
        "sql_execute", "execute_sql", "db.write", "db.insert", "db.update",
        "db.delete", "query_database", "run_query",
    }
    if name in db_writes or name.startswith("db.") or name.startswith("sql."):
        sql = str(ev.tool_args.get("query", "") or ev.tool_args.get("sql", ""))
        # Look for table name in INSERT/UPDATE/DELETE
        m = re.search(
            r"(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            sql, re.IGNORECASE,
        )
        if m:
            return [f"db.{m.group(1).lower()}:w"]
        return ["db.unknown:w"]
    return None


def _browser_rule(ev: AuditEvent) -> Optional[list[str]]:
    """Browser-action tools (click, type, navigate)."""
    name = ev.tool_name.lower()
    if name.startswith("browser_") or name.startswith("browser."):
        url = str(ev.tool_args.get("url") or ev.tool_args.get("selector") or name)
        url_safe = re.sub(r"[^a-zA-Z0-9._-]", "_", url)[:60]
        return [f"repo.browser.{url_safe}:w"]
    return None


def _generic_write_rule(ev: AuditEvent) -> Optional[list[str]]:
    """Last-resort fallback for any tool whose name suggests a write."""
    name = ev.tool_name.lower()
    write_kws = ("write", "edit", "create", "update", "delete", "send", "post", "publish")
    if any(kw in name for kw in write_kws):
        # If we have a path-shaped arg, use it
        for k in ("path", "file_path", "filename", "filepath", "url", "endpoint", "key", "id"):
            if k in ev.tool_args:
                v = re.sub(r"[^a-zA-Z0-9._/-]", "_", str(ev.tool_args[k]))[:80]
                return [f"tool.{name}.{v}:w"]
        return [f"tool.{name}:w"]
    return None


# Built-in defaults, tried after any user-registered rules.
_DEFAULTS: list[ScopeRule] = [
    _filesystem_rule,
    _shell_rule,
    _http_rule,
    _db_rule,
    _browser_rule,
    _generic_write_rule,
]


def infer_scope(ev: AuditEvent) -> list[str]:
    """Return a list of scope strings for an AuditEvent.

    Tries user-registered rules first, then built-in defaults. If no
    rule matches, returns an empty list (caller can decide what to do).
    """
    for rule in _RULES + _DEFAULTS:
        result = rule(ev)
        if result is not None:
            return result
    return []


def annotate_events(events: list[AuditEvent]) -> list[AuditEvent]:
    """Fill in the .scope_inferred field on each event in place. Returns
    the same list for convenience."""
    for ev in events:
        if not ev.scope_inferred:
            ev.scope_inferred = infer_scope(ev)
    return events
