"""Policy registry + the user-facing ``synapse.MergePolicy.*`` namespace.

The ``MergePolicy`` class itself is the ABC. The user-facing constants
live as class-level attributes so ``synapse.MergePolicy.redirect`` works
ergonomically without users instantiating policies themselves.

    synapse.install(merge_policy=synapse.MergePolicy.redirect)
    synapse.install(merge_policy=synapse.MergePolicy.auto_merge)

For custom policies, subclass ``MergePolicy`` and pass an instance:

    class MyPolicy(synapse.MergePolicy):
        async def resolve(self, handle, conflicts, proposed_action=None):
            ...
    synapse.install(merge_policy=MyPolicy())
"""
from __future__ import annotations

from typing import Optional, Union

from .base import MergePolicy
from .builtin import (
    AbortPolicy,
    AutoMergePolicy,
    NoOpPolicy,
    RedirectPolicy,
    WaitPolicy,
)


# Singleton instances — the canonical values for ``synapse.MergePolicy.*``
_REDIRECT = RedirectPolicy()
_WAIT = WaitPolicy()
_ABORT = AbortPolicy()
_AUTO_MERGE = AutoMergePolicy()
_NO_OP = NoOpPolicy()


# Attach singletons as class-level attributes on the ABC. After this
# module is imported, ``MergePolicy.redirect`` etc. resolve to the
# singletons. The ABC's ``resolve()`` abstract method still works for
# subclasses (singletons are instances of concrete subclasses, not the
# ABC itself).
MergePolicy.redirect = _REDIRECT          # type: ignore[attr-defined]
MergePolicy.wait = _WAIT                  # type: ignore[attr-defined]
MergePolicy.abort = _ABORT                # type: ignore[attr-defined]
MergePolicy.auto_merge = _AUTO_MERGE      # type: ignore[attr-defined]
MergePolicy.no_op = _NO_OP                # type: ignore[attr-defined]


PolicyLike = Union[MergePolicy, str, None]


def resolve_policy(spec: PolicyLike) -> Optional[MergePolicy]:
    """Coerce ``spec`` into a MergePolicy instance.

    Accepts:
      - None -> None (means "no policy configured" — caller decides default)
      - MergePolicy instance -> returned as-is
      - string ("redirect" / "wait" / "abort" / "auto_merge" / "no_op")
        -> the matching singleton
    """
    if spec is None:
        return None
    if isinstance(spec, MergePolicy):
        return spec
    if isinstance(spec, str):
        s = spec.replace("-", "_").strip().lower()
        return {
            "redirect": _REDIRECT,
            "wait": _WAIT,
            "abort": _ABORT,
            "auto_merge": _AUTO_MERGE,
            "automerge": _AUTO_MERGE,
            "merge": _AUTO_MERGE,
            "no_op": _NO_OP,
            "noop": _NO_OP,
        }.get(s)
    raise TypeError(
        f"merge_policy must be None | str | MergePolicy, got {type(spec).__name__}"
    )
