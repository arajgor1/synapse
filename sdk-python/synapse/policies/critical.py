"""Critical-scope matcher.

A ``critical_scopes`` list is a set of glob patterns (e.g. ``billing.*``,
``prod.deploy.*``). When any of them match a scope on a CONFLICT-bearing
intention, the system forces ``MergePolicy.abort`` regardless of the
configured policy. Hard guardrail for production-sensitive scopes.
"""
from __future__ import annotations

import fnmatch
from typing import Iterable, Optional


def normalize_critical_scopes(specs: Optional[Iterable[str]]) -> list[str]:
    """Normalize the user's input — strip whitespace, drop empties."""
    if not specs:
        return []
    out = []
    for s in specs:
        s = (s or "").strip()
        if s:
            out.append(s)
    return out


def critical_scope_match(
    intention_scopes: Iterable[str],
    critical_patterns: Iterable[str],
) -> Optional[str]:
    """Return the first matched pattern, or None.

    Strips the modifier suffix (``:r`` / ``:w``) before matching so a
    pattern like ``billing.*`` matches both ``billing.charge:w`` and
    ``billing.charge:r``.
    """
    for scope in intention_scopes:
        # Strip modifier (last :token)
        base = scope.split(":")[0] if ":" in scope else scope
        for pattern in critical_patterns:
            pat_base = pattern.split(":")[0] if ":" in pattern else pattern
            if fnmatch.fnmatchcase(base, pat_base):
                return pattern
    return None
