"""Sigma-retire platform-scope gate tests (WS-M M3.1 / lld/39 §3.5).

The sigma store is fleet-global (NOT tenant-partitioned): retiring a rule strips it
for EVERY tenant. So ``PATCH /v1/sigma-rules/{id}`` must be gated at ``require_platform``
— NOT ``require_role`` — or any tenant-admin could disable a detection rule fleet-wide
(the disable-switch ADR-034 forbids, via the CRUD door). These tests PIN platform-vs-
tenant: a merely-tenant-scoped ``admin`` (not ``_platform``) gets 403.
"""
from __future__ import annotations

import inspect

import boto3
import pytest
from fastapi import HTTPException
from moto import mock_aws
from unittest.mock import AsyncMock, patch

from app.api import routes as R
from app.api.deps import OperatorContext, require_platform
from app.config import settings
from tests.mt_helpers import create_mt_tables


def _ctx(is_platform: bool, role: str = "admin", tenant_id: str = "t_a") -> OperatorContext:
    return OperatorContext(sub="op-x", tenant_id=tenant_id, role=role,
                           email="op@x", is_platform=is_platform)


# --------------------------------------------------------------------------- #
# (wiring) the route carries require_platform, NOT require_role — the wrong-scope
# trap (copying delete_feedback_subject's tenant scope here) would fail this.
# --------------------------------------------------------------------------- #
def test_update_sigma_rule_gated_by_require_platform():
    dep = inspect.signature(R.update_sigma_rule).parameters["ctx"].default.dependency
    assert getattr(dep, "__name__", "") == "require_platform"


# --------------------------------------------------------------------------- #
# (behaviour) platform vs tenant vs un-roled
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_sigma_retire_platform_operator_200():
    """A real _platform operator can retire a rule (the epoch bump rides behind the
    same door)."""
    svc = AsyncMock()
    svc.update_rule_status = AsyncMock(return_value=True)
    with patch("app.services.sigma_rules_service.SigmaRulesService", return_value=svc):
        out = await R.update_sigma_rule("rule-1", {"status": "disabled"},
                                        ctx=_ctx(is_platform=True))
    assert out["success"] is True
    assert out["status"] == "disabled"


@pytest.mark.asyncio
async def test_sigma_retire_bump_enforcement_version_behind_platform_gate():
    """The PATCH handler and the _bump_enforcement_version epoch write are one call
    chain behind one door — driving the handler drives update_rule_status (which
    bumps). We assert the service method (which internally bumps) is reached only
    with a platform ctx."""
    svc = AsyncMock()
    svc.update_rule_status = AsyncMock(return_value=True)
    with patch("app.services.sigma_rules_service.SigmaRulesService", return_value=svc):
        await R.update_sigma_rule("rule-1", {"status": "enabled"}, ctx=_ctx(is_platform=True))
    svc.update_rule_status.assert_awaited_once()


# The 403 paths exercise the require_platform DEPENDENCY (resolve_operator_tenant +
# is_platform check), driven with a stubbed ALB claims override + a moto-backed
# member store (mirrors test_multitenancy_quota's mt_env).
@pytest.fixture
def _mt_members(monkeypatch):
    import app.api.deps as deps
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SECURITY_TOKEN", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        create_mt_tables(ddb)
        import app.utils.clients as clients
        import app.services.tenant_service as ts
        clients._registry = None
        ts._tenant_store = None
        ts._member_store = None
        from app.services.tenant_service import get_member_store
        yield deps, get_member_store()
    deps._alb_claims_override = None


@pytest.mark.asyncio
async def test_sigma_retire_unroled_403(_mt_members):
    """An operator with no _platform membership → 403 from require_platform."""
    deps, members = _mt_members
    deps._alb_claims_override = lambda req: {"sub": "op_unroled", "email": "u@x"}
    members.add("op_unroled", "t_cust", role="viewer", is_primary=True)

    class Req:
        headers = {}
    with pytest.raises(HTTPException) as ei:
        await require_platform(Req())
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_sigma_retire_tenant_admin_403(_mt_members):
    """A tenant-scoped ADMIN (not _platform) is STILL 403 — this is what pins
    platform-vs-tenant. A require_role('admin') gate here would wrongly let them
    disable a fleet-wide detection rule."""
    deps, members = _mt_members
    deps._alb_claims_override = lambda req: {"sub": "op_tadmin", "email": "a@x"}
    members.add("op_tadmin", "t_cust", role="admin", is_primary=True)

    class Req:
        headers = {}
    with pytest.raises(HTTPException) as ei:
        await require_platform(Req())
    assert ei.value.status_code == 403
