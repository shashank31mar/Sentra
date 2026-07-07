"""WS-N N0.3 — the `_platform` mis-provisioning guardrail.

Verifies the alarm-only (never-block) detection of an operator holding BOTH the
`_platform` fleet-metrics grant AND a customer membership — the provisioning-anomaly
fingerprint. The guard emits a CloudWatch metric + an audit row, but must NEVER raise
(a monitor cannot break authentication).
"""
from unittest.mock import patch

import pytest

from app.api import platform_guard


class TestDualMembershipDetection:
    def test_dual_membership_operator_flagged(self):
        """_platform + a customer tenant → flagged True, metric + audit emitted."""
        with patch.object(platform_guard, "_emit_metric") as m_metric, \
             patch.object(platform_guard, "_write_audit") as m_audit:
            flagged = platform_guard.check_platform_membership_anomaly(
                operator_sub="op-dual",
                is_platform=True,
                customer_tenant_ids=["t_customer_a"],
            )
        assert flagged is True
        m_metric.assert_called_once_with("op-dual")
        m_audit.assert_called_once()

    def test_platform_only_operator_not_flagged(self):
        """A clean AegionAI staffer (_platform, no customer tenant) → NOT flagged."""
        with patch.object(platform_guard, "_emit_metric") as m_metric, \
             patch.object(platform_guard, "_write_audit") as m_audit:
            flagged = platform_guard.check_platform_membership_anomaly(
                operator_sub="op-platform",
                is_platform=True,
                customer_tenant_ids=[],
            )
        assert flagged is False
        m_metric.assert_not_called()
        m_audit.assert_not_called()

    def test_customer_only_operator_not_flagged(self):
        """A normal customer operator (no _platform) → NOT flagged."""
        with patch.object(platform_guard, "_emit_metric") as m_metric, \
             patch.object(platform_guard, "_write_audit") as m_audit:
            flagged = platform_guard.check_platform_membership_anomaly(
                operator_sub="op-customer",
                is_platform=False,
                customer_tenant_ids=["t_customer_a", "t_customer_b"],
            )
        assert flagged is False
        m_metric.assert_not_called()
        m_audit.assert_not_called()


class TestGuardNeverBlocks:
    """The guard is a monitor — a failure in metric/audit emission must not raise
    (fail-open on the guard; the tenant-scope binding is the real access control)."""

    def test_metric_failure_does_not_raise(self):
        with patch.object(platform_guard, "_cw", side_effect=RuntimeError("cw down")), \
             patch.object(platform_guard, "_write_audit"):
            # Must not raise even though the CloudWatch client blows up.
            flagged = platform_guard.check_platform_membership_anomaly(
                operator_sub="op-dual",
                is_platform=True,
                customer_tenant_ids=["t_customer_a"],
            )
        assert flagged is True  # still flags; emission is best-effort

    def test_audit_failure_does_not_raise(self):
        with patch.object(platform_guard, "_emit_metric"), \
             patch("app.services.platform_audit.get_platform_audit_store",
                   side_effect=RuntimeError("ddb down")):
            flagged = platform_guard.check_platform_membership_anomaly(
                operator_sub="op-dual",
                is_platform=True,
                customer_tenant_ids=["t_customer_a"],
            )
        assert flagged is True


class TestPlatformFleetReadEmitsAudit:
    """N0.3 acceptance: a flagged anomaly writes to the platform audit ledger with
    the anomaly shape (decision=FLAGGED, read_type=anomaly, target=_platform)."""

    def test_platform_dual_membership_writes_audit_row(self):
        with patch.object(platform_guard, "_emit_metric"), \
             patch("app.services.platform_audit.get_platform_audit_store") as m_store:
            platform_guard.check_platform_membership_anomaly(
                operator_sub="op-dual",
                is_platform=True,
                customer_tenant_ids=["t_a"],
            )
        rec = m_store.return_value.record
        rec.assert_called_once()
        kwargs = rec.call_args.kwargs
        assert kwargs["operator_sub"] == "op-dual"
        assert kwargs["target_tenant"] == "_platform"
        assert kwargs["decision"] == "FLAGGED"
        assert kwargs["read_type"] == "anomaly"
        assert "platform_dual_membership" in kwargs["what"]
        assert "t_a" in kwargs["what"]
