"""WS-L M1.6 / M5 — the per-node MetricsPublisher contract + the FP-budget gate.

`publish_node_metrics` is off the response path and self-guarding (never raises into
the verdict). M5.3's FP-budget gate blocks enforce-graduation above the budget.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.detection_eval import DetectorScore, fp_budget_gate
from app.utils.metrics_publisher import MetricsPublisher


# ------------------------------------------------------------------ M1.6
@pytest.mark.asyncio
async def test_publish_node_metrics_shape():
    """publish_node_metrics posts a data point carrying the node_source + phase
    dimensions and the decision/latency values (spy on the CloudWatch client)."""
    pub = MetricsPublisher.__new__(MetricsPublisher)
    pub.namespace = "Sentra/SecurityController"
    pub.cloudwatch = MagicMock()

    await pub.publish_node_metrics("sentra.indirect_injection", "content", "DENY", 12.3)

    pub.cloudwatch.put_metric_data.assert_called_once()
    kwargs = pub.cloudwatch.put_metric_data.call_args.kwargs
    metric_names = {m["MetricName"] for m in kwargs["MetricData"]}
    assert "NodeLatencyMs" in metric_names and "NodeDecision" in metric_names
    # every metric carries the node_source + phase dimensions.
    for m in kwargs["MetricData"]:
        dims = {d["Name"]: d["Value"] for d in m["Dimensions"]}
        assert dims["node_source"] == "sentra.indirect_injection"
        assert dims["phase"] == "content"
    latency = next(m for m in kwargs["MetricData"] if m["MetricName"] == "NodeLatencyMs")
    assert latency["Value"] == 12.3
    decision = next(m for m in kwargs["MetricData"] if m["MetricName"] == "NodeDecision")
    dims = {d["Name"]: d["Value"] for d in decision["Dimensions"]}
    assert dims["decision"] == "DENY"


@pytest.mark.asyncio
async def test_publish_node_metrics_never_raises():
    """A raise inside the publish is swallowed (off-path; never blocks a verdict)."""
    pub = MetricsPublisher.__new__(MetricsPublisher)
    pub.namespace = "Sentra/SecurityController"
    pub.cloudwatch = MagicMock()
    pub.cloudwatch.put_metric_data.side_effect = RuntimeError("cloudwatch down")

    # must NOT raise
    await pub.publish_node_metrics("sentra.memory", "memory", "ALLOW", 1.0)


# ------------------------------------------------------------------ M5.1 (seam)
@pytest.mark.asyncio
async def test_every_node_emits_latency_metric():
    """Running a content DAG emits a publish_node_metrics call per node with the
    right node_source/phase dimensions (spy on the publisher)."""
    from unittest.mock import AsyncMock, Mock
    from app.api.models import ValidationRequest, ValidationResult
    from app.services.validation_service import ValidationService
    from app.validators.distilled_classifier import DistilledClassifier

    with patch.object(ValidationService, "__init__", lambda self: None):
        svc = ValidationService()

    session = {"session_id": "s", "agent_id": "a", "trust_score": 80.0, "action_count": 1}
    allow = ValidationResult(decision="ALLOW", reason="ok", should_deny=False)
    svc.trust_checker = Mock(); svc.trust_checker.check = AsyncMock(return_value=allow)
    svc.policy_engine = Mock()
    svc.policy_engine.get_agent_policy = AsyncMock(return_value={"rate_limit": 100})
    svc.abuse_detector = Mock()
    svc.abuse_detector.check_rate_limit = AsyncMock(return_value=allow)
    svc.sigma_engine = Mock()
    svc.sigma_engine.match_rules = AsyncMock(return_value=allow)
    svc.ml_classifier = Mock()
    svc.ml_classifier.validate = AsyncMock(return_value=ValidationResult.abstain("off"))
    svc.distilled_classifier = DistilledClassifier()
    svc.metrics_publisher = Mock()
    svc.metrics_publisher.publish_node_metrics = AsyncMock()

    # A benign content request → the D2 node set runs.
    req = ValidationRequest(
        request_id="r", session_id="s", agent_id="a", tool_name="ingest",
        tool_params={}, user_input="", timestamp="2026-07-03T00:00:00Z",
        operation_type="READ", phase="content", content_text="benign doc",
    )
    # NER barrier reads phi_ner — patch it to a no-op so the content node runs offline.
    with patch("app.redaction.phi_ner.get_phi_ner_client") as ner:
        view = Mock(); view.text = "benign doc"; view.found_classes = []
        ner.return_value.redact_free_text = Mock(return_value=view)
        await svc._run_validation_pipeline(req, session)

    called_sources = {
        c.kwargs["node_source"] for c in svc.metrics_publisher.publish_node_metrics.call_args_list
    }
    # the content D2 detector node emitted a per-node metric.
    assert "sentra.indirect_injection" in called_sources
    # every metric was tagged phase=content.
    for c in svc.metrics_publisher.publish_node_metrics.call_args_list:
        assert c.kwargs["phase"] == "content"


# ------------------------------------------------------------------ M5.3 FP-budget gate
def test_fp_budget_gate_blocks_enforce():
    """A detector whose FP-rate exceeds the budget cannot graduate to enforce; below
    budget it can (R5-C)."""
    # 5 FP / 95 TN → 5% FP-rate.
    over = DetectorScore(tp=10, fp=5, tn=95, fn=0)
    assert over.fp_rate == pytest.approx(0.05)
    assert fp_budget_gate(over, fp_budget=0.02) is False   # over budget → blocked
    assert fp_budget_gate(over, fp_budget=0.10) is True    # under budget → may enforce
