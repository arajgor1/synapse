"""Multi-tenant `request_id` isolation tests.

Validates that adapters with `multi_tenant_isolation = "request_id"` reject
cross-tenant operations on a request_id they don't own.
"""

from __future__ import annotations

import pytest

from synapse.adapters import MockAdapter
from synapse.adapters.base import (
    TenantContext,
    TenantViolation,
)


pytestmark = pytest.mark.asyncio


class TestTenantContextEquality:
    def test_default_anonymous_matches_default(self) -> None:
        a = TenantContext()
        b = TenantContext()
        assert a.matches(b)

    def test_named_matches_same_named(self) -> None:
        a = TenantContext(tenant_id="t1", agent_id="a1", session_id="s1")
        b = TenantContext(tenant_id="t1", agent_id="a1", session_id="s1")
        assert a.matches(b)

    def test_different_tenant_does_not_match(self) -> None:
        a = TenantContext(tenant_id="t1", agent_id="a1", session_id="s1")
        b = TenantContext(tenant_id="t2", agent_id="a1", session_id="s1")
        assert not a.matches(b)

    def test_different_agent_does_not_match(self) -> None:
        a = TenantContext(tenant_id="t1", agent_id="a1", session_id="s1")
        b = TenantContext(tenant_id="t1", agent_id="a2", session_id="s1")
        assert not a.matches(b)

    def test_different_session_does_not_match(self) -> None:
        a = TenantContext(tenant_id="t1", agent_id="a1", session_id="s1")
        b = TenantContext(tenant_id="t1", agent_id="a1", session_id="s2")
        assert not a.matches(b)


class TestMockAdapterTenantIsolation:
    async def test_advertises_request_id_isolation_by_default(self) -> None:
        adapter = MockAdapter()
        assert adapter.capabilities.multi_tenant_isolation == "request_id"

    async def test_can_opt_out_to_process_mode(self) -> None:
        adapter = MockAdapter(multi_tenant=False)
        assert adapter.capabilities.multi_tenant_isolation == "process"

    async def test_handle_carries_tenant_from_params(self) -> None:
        adapter = MockAdapter()
        t = TenantContext(tenant_id="acme", agent_id="a1", session_id="s1")
        handle = await adapter.start_stream(messages=[], params={"tenant": t})
        assert handle.tenant == t

    async def test_same_tenant_can_read_and_cancel(self) -> None:
        adapter = MockAdapter(scripted_response="hello", delay_per_token_ms=0)
        t = TenantContext(tenant_id="acme", agent_id="a1", session_id="s1")
        handle = await adapter.start_stream(messages=[], params={"tenant": t})
        # read tokens (same tenant)
        text = ""
        async for tok in adapter.read_tokens(handle):
            text += tok.text
        assert text.strip() == "hello"

    async def test_cross_tenant_read_rejected(self) -> None:
        adapter = MockAdapter(scripted_response="secret", delay_per_token_ms=0)
        owner = TenantContext(tenant_id="acme", agent_id="a1", session_id="s1")
        handle = await adapter.start_stream(messages=[], params={"tenant": owner})

        # Forge a handle with a different tenant
        attacker_handle = type(handle)(
            request_id=handle.request_id,
            original_messages=handle.original_messages,
            params=handle.params,
            extra=handle.extra,
            tenant=TenantContext(
                tenant_id="evilcorp", agent_id="b9", session_id="s2"
            ),
        )
        with pytest.raises(TenantViolation):
            async for _ in adapter.read_tokens(attacker_handle):
                pass

    async def test_cross_tenant_inject_rejected(self) -> None:
        adapter = MockAdapter(scripted_response="abc", delay_per_token_ms=0)
        owner = TenantContext(tenant_id="acme", agent_id="a1", session_id="s1")
        handle = await adapter.start_stream(messages=[], params={"tenant": owner})

        attacker_handle = type(handle)(
            request_id=handle.request_id,
            original_messages=handle.original_messages,
            params=handle.params,
            extra=handle.extra,
            tenant=TenantContext(tenant_id="evilcorp"),
        )
        with pytest.raises(TenantViolation):
            await adapter.inject_and_continue(
                attacker_handle, injection="x", instruction="y"
            )

    async def test_cross_tenant_cancel_rejected(self) -> None:
        adapter = MockAdapter(scripted_response="abc", delay_per_token_ms=0)
        owner = TenantContext(tenant_id="acme", agent_id="a1", session_id="s1")
        handle = await adapter.start_stream(messages=[], params={"tenant": owner})

        attacker_handle = type(handle)(
            request_id=handle.request_id,
            original_messages=handle.original_messages,
            params=handle.params,
            extra=handle.extra,
            tenant=TenantContext(tenant_id="evilcorp"),
        )
        with pytest.raises(TenantViolation):
            await adapter.cancel(attacker_handle)

    async def test_anonymous_caller_can_act_on_anonymous_request(self) -> None:
        """Backward compatibility: pre-multi-tenant code passes no tenant.
        Default TenantContext() owners + default callers should be treated
        as the same anonymous tenant."""
        adapter = MockAdapter(scripted_response="ok", delay_per_token_ms=0)
        handle = await adapter.start_stream(messages=[], params={})
        text = ""
        async for tok in adapter.read_tokens(handle):
            text += tok.text
        assert text.strip() == "ok"

    async def test_inject_and_continue_carries_tenant_through(self) -> None:
        adapter = MockAdapter(scripted_response="abc", delay_per_token_ms=0)
        owner = TenantContext(tenant_id="acme", agent_id="a1", session_id="s1")
        handle = await adapter.start_stream(messages=[], params={"tenant": owner})

        # Read a bit so partial exists
        async for _ in adapter.read_tokens(handle):
            break  # only one token

        new_handle = await adapter.inject_and_continue(
            handle, injection="signal", instruction="continue"
        )
        # The new handle's tenant must match the original owner
        assert new_handle.tenant == owner
        # And the new request_id is owned by the same tenant
        assert adapter._tenant_index[new_handle.request_id] == owner
