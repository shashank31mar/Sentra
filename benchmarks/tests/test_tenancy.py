"""The ``_benchmark`` reserved tenant — the one and only ``app/`` source edit in
this build.

LLD 41 §4.7 · WS-B B3 · upstream owner LLD 26 §3.7 (``RESERVED_TENANT_IDS``).

Reserving the id is what makes every row the rig can cause separable by partition
key: ``tenancy.compose()`` prefixes it, so a row that leaks past the null objects
is identifiable after the fact and deletable as a unit, and no customer can mint
the id and collide with it.
"""
from __future__ import annotations

import pytest

from app.utils import tenancy
from benchmarks.core import isolation


def test_benchmark_tenant_is_reserved():
    """``is_reserved_tenant("_benchmark")`` is True, and the id the rig binds is
    the id that is reserved (the two constants are not allowed to drift)."""
    assert tenancy.is_reserved_tenant("_benchmark") is True
    assert tenancy.BENCHMARK_PSEUDO_TENANT == "_benchmark"
    assert isolation.BENCHMARK_TENANT == tenancy.BENCHMARK_PSEUDO_TENANT
    assert tenancy.BENCHMARK_PSEUDO_TENANT in tenancy.RESERVED_TENANT_IDS


@pytest.mark.parametrize(
    "existing",
    ["default", "_unverified", "_platform", "_revocation"],
)
def test_reserved_set_membership_unchanged_for_existing(existing):
    """The four pre-existing ids are still members. A frozenset edit that drops
    one is silent and catastrophic — nothing else in the tree would notice until
    a customer minted ``_platform``."""
    assert existing in tenancy.RESERVED_TENANT_IDS
    assert tenancy.is_reserved_tenant(existing) is True


def test_reserved_set_is_exactly_five():
    """Membership is pinned by count as well as by name, so an accidental
    addition is as visible as an accidental removal."""
    assert tenancy.RESERVED_TENANT_IDS == frozenset(
        {"default", "_unverified", "_platform", "_revocation", "_benchmark"}
    )


def test_customer_cannot_mint_benchmark_tenant():
    """The production path that enforces ``is_reserved_tenant`` on tenant
    creation rejects ``_benchmark``.

    ``TenantStore.__init__`` builds a DynamoDB resource, and the reserved-id
    check is the first statement of ``create()`` — before ``self._table()`` is
    ever touched. Constructing the instance without ``__init__`` therefore
    exercises the real guard with no AWS dependency at all, rather than
    re-implementing the check in the test.
    """
    from app.services.tenant_service import TenantError, TenantStore

    store = object.__new__(TenantStore)

    with pytest.raises(TenantError) as excinfo:
        store.create(display_name="X", tenant_id="_benchmark")
    assert "reserved" in str(excinfo.value)

    # And a non-reserved id gets past the reserved check to fail on a different
    # rule — so the assertion above is about the reservation, not about `create`
    # rejecting everything it is handed.
    with pytest.raises(TenantError) as excinfo:
        store.create(display_name="X", tenant_id="Not-A-Slug")
    assert "reserved" not in str(excinfo.value)
    assert "slug" in str(excinfo.value)


def test_enforce_binds_and_resets_tenant(hermetic_env):
    """``enforce()`` binds ``_benchmark`` via the existing contextvar and hands
    back the Token, so the run can unwind the binding rather than leaking it into
    whatever runs next in this process."""
    import botocore.session

    hermetic_env.setattr(botocore.session.Session, "get_credentials", lambda _s: None)

    previous = tenancy.current_tenant()
    record = isolation.enforce()
    try:
        assert tenancy.current_tenant() == "_benchmark"
        assert record.tenant == "_benchmark"
        assert record.tenant_token is not None
        # Every key the rig composes carries the prefix, so a leaked row is
        # identifiable after the fact.
        assert tenancy.compose(tenancy.current_tenant(), "sess-1") == "_benchmark#sess-1"
    finally:
        record.release()

    assert tenancy.current_tenant() == previous
    # release() is idempotent — a run that unwinds twice must not raise.
    record.release()
    assert tenancy.current_tenant() == previous
