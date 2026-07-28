"""The ``_benchmark`` reserved-tenant contract, end to end.

LLD 41 §4.7 · WS-B B6 (shared contract: the ``_benchmark`` reserved tenant).

The full version drives a real in-process validate through WS-D's ``GuardClient``
and asserts every row the rig can cause carries the ``_benchmark`` prefix. WS-D
has not landed, so that half is **skipped with an explicit reason and kept in the
tree** rather than deleted — it activates on its own once the seam exists.

What can be discharged today is discharged today: the binding itself, the
composite-key prefix every store keys off, and the reservation.
"""
from __future__ import annotations

import importlib.util

import pytest

from benchmarks.core import isolation

#: WS-D's engine seam. When this module exists, the skipped test below becomes
#: live without anyone having to remember it.
WS_D_GUARD_CLIENT = "benchmarks.core.guard_client"


def _ws_d_available() -> bool:
    try:
        return importlib.util.find_spec(WS_D_GUARD_CLIENT) is not None
    except (ImportError, ValueError):
        return False


@pytest.fixture
def isolated(hermetic_env):
    import botocore.session

    hermetic_env.setattr(botocore.session.Session, "get_credentials", lambda _s: None)
    record = isolation.enforce()
    yield record
    record.release()


def test_enforce_binds_the_reserved_benchmark_tenant(isolated):
    """After ``enforce()`` the whole run is inside the ``_benchmark`` tenant, and
    that tenant is one no customer can hold."""
    from app.utils import tenancy

    assert tenancy.current_tenant() == "_benchmark"
    assert tenancy.is_reserved_tenant(tenancy.current_tenant()) is True
    assert isolated.tenant == "_benchmark"


def test_every_composite_key_carries_the_benchmark_prefix(isolated):
    """``tenancy.compose()`` is the canonical join every v2 partition and GSI key
    uses, so a row written under the binding is separable — identifiable after the
    fact and deletable as a unit."""
    from app.utils import tenancy

    tenant = tenancy.current_tenant()
    for value in ("sess-abc", "agent-1", "2026-07-27"):
        assert tenancy.compose(tenant, value) == f"_benchmark#{value}"

    # The signal store's base partition key is the composite one, so this is the
    # shape a leaked signal row would actually carry.
    assert tenancy.signal_pk_value("sess-abc", tenant="_benchmark").endswith("sess-abc")


@pytest.mark.skipif(
    not _ws_d_available(),
    reason=(
        "WS-D's GuardClient / BenchmarkSessionStore has not landed "
        f"({WS_D_GUARD_CLIENT} not importable), so no in-process validate can be "
        "driven yet. Kept in the tree deliberately (LLD 41 §4.7 / WS-B B6): it "
        "activates automatically once the seam exists."
    ),
)
def test_driven_validate_writes_only_under_the_benchmark_tenant(isolated):
    """Drive a real in-process validate and assert every row the rig can cause
    carries the ``_benchmark`` prefix."""
    from app.utils import tenancy

    from benchmarks.core.guard_client import GuardClient  # type: ignore[import-not-found]

    client = GuardClient()
    client.validate(
        agent_id="bench-agent",
        tool_name="read_file",
        parameters={"path": "/tmp/benchmark"},
    )

    written = client.written_partition_keys()
    assert written, "the driven validate wrote nothing — the assertion would be vacuous"
    assert all(key.startswith("_benchmark#") for key in written)
    assert tenancy.is_reserved_tenant("_benchmark") is True
