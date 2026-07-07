"""WS-N N0.3 — the ``_platform`` mis-provisioning guardrail.

`_platform` is AegionAI's reserved cross-tenant OPERATIONAL-fleet grant (metrics /
metadata across tenants — threats/agents/quarantine counts, cloud distribution — NOT
customer content). It is server-derived from membership (`deps.py`), so a client
cannot spoof it. But WS-N widened its blast radius from mutations to every operational
read, so a MIS-PROVISIONED grant (a bad invite/redeem path that attaches `_platform`
to an account that is ALSO a normal customer member) is a provisioning anomaly worth
catching: such an operator would silently gain the cross-tenant fleet-metrics view.

The intended shapes are disjoint: AegionAI staff are ``_platform``-only; customers are
customer-tenant-only. An account holding BOTH is the anomaly fingerprint.

Behavior (founder 2026-07-07): **alarm-only, still serve.** Because the grant is not
spoofable, a dual membership is a config error to fix — not an active attack — so we
DETECT + emit a CloudWatch metric (alarmed in ``monitoring_stack.py``) + write an
immutable audit row, but we do NOT block the request. This is fire-and-forget: a guard
failure must never break authentication (fail-open on the GUARD is correct here — the
guard is a monitor, not the access-control decision, which the tenant-scope binding
already enforces).
"""
from __future__ import annotations

import logging
from typing import List

import boto3
from botocore.exceptions import ClientError

from app.config import settings

logger = logging.getLogger(__name__)

_METRIC_NAMESPACE = "Sentra/SecurityController"
# The metric the CDK alarm watches — `{prefix}-sc-platform-dual-membership` in
# monitoring_stack.py (SnsAction → critical_alerts_topic, threshold >=1, 1 datapoint).
# A single datapoint (>=1) means a dual-membership operator authenticated → page ops.
PLATFORM_DUAL_MEMBERSHIP_METRIC = "PlatformDualMembershipDetected"

_cloudwatch = None


def _cw():
    """Lazily-built CloudWatch client (kept off import so tests/CDK synth don't need creds)."""
    global _cloudwatch
    if _cloudwatch is None:
        _cloudwatch = boto3.client("cloudwatch", region_name=settings.aws_region)
    return _cloudwatch


def check_platform_membership_anomaly(
    *, operator_sub: str, is_platform: bool, customer_tenant_ids: List[str]
) -> bool:
    """Flag an operator that holds BOTH the ``_platform`` grant AND ≥1 customer
    membership (the mis-provisioning fingerprint).

    Returns ``True`` when the anomaly is present (for tests / callers that want the
    signal), ``False`` otherwise. Emits a CloudWatch metric + an audit row as a
    side effect when flagged. **Never raises** — a guard failure must not break auth.
    """
    if not (is_platform and customer_tenant_ids):
        return False

    logger.warning(
        "PLATFORM_DUAL_MEMBERSHIP operator=%s holds _platform AND customer tenants=%s "
        "(mis-provisioning anomaly — fleet-metrics grant should be _platform-only)",
        operator_sub, customer_tenant_ids,
    )
    _emit_metric(operator_sub)
    _write_audit(operator_sub, customer_tenant_ids)
    return True


def _emit_metric(operator_sub: str) -> None:
    """Fire-and-forget CloudWatch datapoint the N0.3 alarm watches. Never raises."""
    try:
        _cw().put_metric_data(
            Namespace=_METRIC_NAMESPACE,
            MetricData=[
                {
                    "MetricName": PLATFORM_DUAL_MEMBERSHIP_METRIC,
                    "Value": 1,
                    "Unit": "Count",
                }
            ],
        )
    except (ClientError, Exception) as e:  # noqa: BLE001 — a monitor must never break auth
        logger.exception("N0.3 dual-membership metric emit failed (non-blocking): %s", e)


def _write_audit(operator_sub: str, customer_tenant_ids: List[str]) -> None:
    """Write an immutable audit row for the anomaly. Reuses the platform audit ledger
    (the same tamper-evident store the cross-tenant reads use). Never raises."""
    try:
        from app.services.platform_audit import get_platform_audit_store
        from app.utils import tenancy

        get_platform_audit_store().record(
            operator_sub=operator_sub,
            target_tenant=tenancy.PLATFORM_TENANT,  # "_platform" — the anomaly is bucketed here
            what=f"platform_dual_membership:{','.join(sorted(customer_tenant_ids))}",
            read_type="anomaly",
            decision="FLAGGED",
            consent_state="n/a-anomaly",
        )
    except Exception as e:  # noqa: BLE001 — audit best-effort; the metric/alarm is the primary signal
        logger.exception("N0.3 dual-membership audit write failed (non-blocking): %s", e)
