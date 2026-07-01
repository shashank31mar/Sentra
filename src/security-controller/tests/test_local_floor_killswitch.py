"""WS-I I5.3 — deterministic local-floor kill-switch semantics (LLD 28 §5.6).

`effective_local_floor_enabled` must combine the fleet flag with the per-tenant
override conservatively: the floor evaluates locally ONLY when BOTH permit it;
either set false routes that tenant to the hosted /v1/validate path. The off-state
is "validate on the server", NEVER "skip validation" (ADR-034) — these tests pin
that the AND-logic can never produce a "skip" outcome (it only ever returns a bool
that selects eval LOCATION).
"""
import pytest

from app.config import settings
from app.utils import tenancy


@pytest.fixture(autouse=True)
def _restore_fleet_flag():
    before = settings.local_floor_enabled
    yield
    settings.local_floor_enabled = before


def test_fleet_on_tenant_inherits_evaluates_local():
    settings.local_floor_enabled = True
    assert tenancy.effective_local_floor_enabled(None) is True


def test_fleet_on_tenant_override_false_routes_hosted():
    # One bad bundle: a single tenant is forced onto the hosted path without a
    # fleet-wide fallback.
    settings.local_floor_enabled = True
    assert tenancy.effective_local_floor_enabled(False) is False


def test_fleet_on_tenant_override_true_evaluates_local():
    settings.local_floor_enabled = True
    assert tenancy.effective_local_floor_enabled(True) is True


def test_fleet_off_overrides_every_tenant():
    # Fleet kill-switch caps EVERY tenant onto the hosted path regardless of a
    # permissive per-tenant override — the incident escape hatch.
    settings.local_floor_enabled = False
    assert tenancy.effective_local_floor_enabled(True) is False
    assert tenancy.effective_local_floor_enabled(None) is False
    assert tenancy.effective_local_floor_enabled(False) is False


def test_result_is_always_bool_never_skip():
    # The function selects eval LOCATION; it must always be a strict bool so a
    # caller can never misread a None/"skip" sentinel as fail-open.
    settings.local_floor_enabled = True
    for override in (None, True, False):
        assert isinstance(tenancy.effective_local_floor_enabled(override), bool)
