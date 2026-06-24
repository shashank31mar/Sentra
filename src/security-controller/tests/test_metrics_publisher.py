"""
Unit Tests for Metrics Publisher

Tests the CloudWatch metrics publishing functionality.
"""
import pytest
from unittest.mock import Mock, patch

from app.utils.metrics_publisher import MetricsPublisher


@pytest.fixture
def metrics_publisher():
    """Create MetricsPublisher with mocked CloudWatch"""
    with patch('app.utils.metrics_publisher.boto3.client') as mock_boto3:
        mock_cw_client = Mock()
        mock_boto3.return_value = mock_cw_client
        publisher = MetricsPublisher()
        publisher.cloudwatch = mock_cw_client
        yield publisher


@pytest.mark.asyncio
async def test_publish_validation_metrics_allow(metrics_publisher):
    """Test publishing metrics for ALLOW decision"""
    await metrics_publisher.publish_validation_metrics(
        decision="ALLOW",
        latency_ms=50.0,
        agent_id="test-agent",
        trust_score=95.0
    )
    
    # Verify CloudWatch was called
    assert metrics_publisher.cloudwatch.put_metric_data.called
    
    # Verify metrics include ValidationsTotal, ValidationLatency, TrustScoreAverage
    call_args = metrics_publisher.cloudwatch.put_metric_data.call_args
    metrics = call_args[1]['MetricData']
    
    metric_names = [m['MetricName'] for m in metrics]
    assert 'ValidationsTotal' in metric_names
    assert 'ValidationLatency' in metric_names
    assert 'TrustScoreAverage' in metric_names


@pytest.mark.asyncio
async def test_publish_validation_metrics_deny(metrics_publisher):
    """Test publishing metrics for DENY decision includes DenyRate"""
    await metrics_publisher.publish_validation_metrics(
        decision="DENY",
        latency_ms=45.0,
        agent_id="test-agent",
        trust_score=75.0
    )
    
    call_args = metrics_publisher.cloudwatch.put_metric_data.call_args
    metrics = call_args[1]['MetricData']
    
    metric_names = [m['MetricName'] for m in metrics]
    assert 'DenyRate' in metric_names


@pytest.mark.asyncio
async def test_publish_session_metrics(metrics_publisher):
    """Test publishing session status metrics"""
    await metrics_publisher.publish_session_metrics(
        quarantined_count=2,
        suspended_count=1
    )
    
    assert metrics_publisher.cloudwatch.put_metric_data.called
    
    call_args = metrics_publisher.cloudwatch.put_metric_data.call_args
    metrics = call_args[1]['MetricData']
    
    metric_names = [m['MetricName'] for m in metrics]
    assert 'QuarantinedSessions' in metric_names
    assert 'SuspendedSessions' in metric_names


@pytest.mark.asyncio
async def test_publish_error_metric(metrics_publisher):
    """Test publishing error metrics"""
    await metrics_publisher.publish_error_metric(error_type="DYNAMODB_ERROR")
    
    assert metrics_publisher.cloudwatch.put_metric_data.called
    
    call_args = metrics_publisher.cloudwatch.put_metric_data.call_args
    metrics = call_args[1]['MetricData']
    
    assert metrics[0]['MetricName'] == 'ValidationErrors'
    assert metrics[0]['Dimensions'][0]['Value'] == 'DYNAMODB_ERROR'


@pytest.mark.asyncio
async def test_metrics_error_does_not_raise(metrics_publisher):
    """Test that metrics publishing errors don't propagate"""
    metrics_publisher.cloudwatch.put_metric_data.side_effect = Exception("CloudWatch error")

    # Should not raise exception (fire-and-forget)
    try:
        await metrics_publisher.publish_validation_metrics(
            decision="ALLOW",
            latency_ms=50.0,
            agent_id="test-agent",
            trust_score=95.0
        )
    except Exception:
        pytest.fail("Metrics publisher should not raise exceptions")


@pytest.mark.asyncio
async def test_publish_quota_exceeded_metric(metrics_publisher):
    """QuotaExceeded carries a single tenant_id dimension (WS-E E2b)."""
    await metrics_publisher.publish_quota_exceeded_metric(tenant_id="t_acme")

    assert metrics_publisher.cloudwatch.put_metric_data.called
    call_args = metrics_publisher.cloudwatch.put_metric_data.call_args
    assert call_args[1]['Namespace'] == 'Sentra/SecurityController'
    metric = call_args[1]['MetricData'][0]
    assert metric['MetricName'] == 'QuotaExceeded'
    assert metric['Value'] == 1 and metric['Unit'] == 'Count'
    dims = {d['Name']: d['Value'] for d in metric['Dimensions']}
    assert dims == {'tenant_id': 't_acme'}


@pytest.mark.asyncio
async def test_publish_quota_exceeded_metric_unknown_tenant(metrics_publisher):
    """A missing tenant_id degrades to '_unknown' (never an empty dimension)."""
    await metrics_publisher.publish_quota_exceeded_metric(tenant_id="")
    metric = metrics_publisher.cloudwatch.put_metric_data.call_args[1]['MetricData'][0]
    assert metric['Dimensions'][0]['Value'] == '_unknown'


@pytest.mark.asyncio
async def test_publish_quota_exceeded_metric_fail_safe(metrics_publisher):
    """A CloudWatch failure never blocks the validate path (fire-and-forget)."""
    metrics_publisher.cloudwatch.put_metric_data.side_effect = Exception("CloudWatch down")
    try:
        await metrics_publisher.publish_quota_exceeded_metric(tenant_id="t_acme")
    except Exception:
        pytest.fail("publish_quota_exceeded_metric must never raise")


@pytest.mark.asyncio
async def test_metrics_include_correct_dimensions(metrics_publisher):
    """Test that metrics include correct dimensions"""
    await metrics_publisher.publish_validation_metrics(
        decision="ALLOW",
        latency_ms=50.0,
        agent_id="customer-query-agent",
        trust_score=95.0
    )
    
    call_args = metrics_publisher.cloudwatch.put_metric_data.call_args
    metrics = call_args[1]['MetricData']
    
    # Find ValidationsTotal metric
    validations_metric = next(m for m in metrics if m['MetricName'] == 'ValidationsTotal')
    
    # Verify dimensions
    dimensions = {d['Name']: d['Value'] for d in validations_metric['Dimensions']}
    assert dimensions['AgentId'] == 'customer-query-agent'
    assert dimensions['Decision'] == 'ALLOW'


@pytest.mark.asyncio
async def test_metrics_use_correct_namespace(metrics_publisher):
    """Test that metrics are published to correct namespace"""
    await metrics_publisher.publish_validation_metrics(
        decision="ALLOW",
        latency_ms=50.0,
        agent_id="test-agent",
        trust_score=95.0
    )
    
    call_args = metrics_publisher.cloudwatch.put_metric_data.call_args
    assert call_args[1]['Namespace'] == 'Sentra/SecurityController'
