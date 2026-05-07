"""Shared multi-tenant isolation helpers for adapters.

Native and Local-API adapters that want to advertise
`multi_tenant_isolation = "request_id"` use the `RequestIdIsolatedMixin` to
get tenant validation on every per-request operation.

Behavior:
- start_stream stamps the `tenant` field on the returned StreamHandle from
  the caller-supplied TenantContext (or anonymous if none).
- Subsequent ops (read_tokens, inject_and_continue, cancel) call
  `_check_tenant(handle, expected)` to verify the calling tenant matches.
  Mismatch -> TenantViolation.
- Internal `_streams` dict is keyed by request_id but ALSO records the
  TenantContext so checks survive even if the caller mints a fake handle.
"""

from __future__ import annotations

from typing import Any, Optional

from synapse.adapters.base import (
    StreamHandle,
    TenantContext,
    TenantViolation,
)


class RequestIdIsolatedMixin:
    """Mix into an adapter that advertises multi_tenant_isolation='request_id'.

    Adapter MUST:
    - Set `self._tenant_index: dict[str, TenantContext] = {}` in __init__
    - Call `self._stamp_tenant(rid, tenant)` after creating a request
    - Call `self._check_tenant(handle, caller_tenant)` at the start of every
      per-request method (read_tokens, inject_and_continue, cancel)
    - Call `self._release_tenant(rid)` after the stream is fully done
    """

    _tenant_index: dict[str, TenantContext]

    def _stamp_tenant(self, request_id: str, tenant: Optional[TenantContext]) -> None:
        self._tenant_index[request_id] = tenant or TenantContext()

    def _check_tenant(
        self,
        handle: StreamHandle,
        caller_tenant: Optional[TenantContext],
    ) -> None:
        owner = self._tenant_index.get(handle.request_id)
        if owner is None:
            # Unknown request — the underlying op will fail with a useful error
            return
        caller = caller_tenant or handle.tenant or TenantContext()
        if not owner.matches(caller):
            raise TenantViolation(
                f"Cross-tenant access on request_id={handle.request_id}: "
                f"owner={owner} caller={caller}"
            )

    def _release_tenant(self, request_id: str) -> None:
        self._tenant_index.pop(request_id, None)
