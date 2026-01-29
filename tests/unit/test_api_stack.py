"""
Unit tests for API Gateway Stack

Tests API Gateway configuration, endpoints, alarms, and integrations.
Target: >80% code coverage
"""

import aws_cdk as cdk
from aws_cdk.assertions import Template, Match
from stacks.api_stack import ApiStack
from stacks.network_stack import NetworkStack
from stacks.storage_stack import StorageStack
from stacks.compute_stack import ComputeStack
import os


def setup_test_stacks(app):
    """Helper function to create test stack dependencies"""
    os.environ["ENV"] = "dev"
    os.environ["AWS_ACCOUNT_ID"] = "123456789012"
    os.environ["AWS_REGION"] = "us-east-1"
    
    env = cdk.Environment(account="123456789012", region="us-east-1")
    
    # Create prerequisite stacks
    network_stack = NetworkStack(app, "TestNetworkStack", env=env)
    storage_stack = StorageStack(app, "TestStorageStack", env=env)
    compute_stack = ComputeStack(
        app, "TestComputeStack",
        config={},
        network_stack=network_stack,
        storage_stack=storage_stack,
        env=env
    )
    
    # Create API stack
    api_stack = ApiStack(
        app, "TestApiStack",
        network_stack=network_stack,
        compute_stack=compute_stack,
        env=env
    )
    
    return api_stack


def test_api_gateway_created():
    """Test that REST API is created with correct configuration."""
    app = cdk.App()
    stack = setup_test_stacks(app)
    template = Template.from_stack(stack)

    # Verify REST API created
    template.resource_count_is("AWS::ApiGateway::RestApi", 1)
    template.has_resource_properties("AWS::ApiGateway::RestApi", {
        "Name": "sentra-mvp-api"
    })


def test_api_key_and_usage_plan():
    """Test that API key and usage plan are created."""
    app = cdk.App()
    stack = setup_test_stacks(app)
    template = Template.from_stack(stack)

    # Verify API key
    template.resource_count_is("AWS::ApiGateway::ApiKey", 1)

    # Verify usage plan
    template.has_resource_properties("AWS::ApiGateway::UsagePlan", {
        "Quota": {"Limit": 100000, "Period": "MONTH"},
        "Throttle": {"RateLimit": 100, "BurstLimit": 200}
    })


def test_all_8_endpoints_created():
    """Test that all 8 API endpoints are created."""
    app = cdk.App()
    stack = setup_test_stacks(app)
    template = Template.from_stack(stack)

    # Should have at least 8 POST/GET methods (excluding OPTIONS)
    # 1. /v1/health (GET)
    # 2. /v1/validate (POST)
    # 3. /v1/logs (GET)
    # 4. /v1/rollback (POST)
    # 5. /v1/agents/customer-query/query (POST)
    # 6. /v1/agents/customer-query/action (POST)
    # 7. /v1/agents/payment/query (POST)
    # 8. /v1/agents/payment/action (POST)
    template.resource_count_is("AWS::ApiGateway::Method", Match.at_least(8))


def test_public_alb_integration():
    """Test that API Gateway integrates directly with public ALB (no VPC Link)."""
    app = cdk.App()
    stack = setup_test_stacks(app)
    template = Template.from_stack(stack)

    # Verify NO VPC Link exists (architecture change per ADR-003 v2)
    template.resource_count_is("AWS::ApiGateway::VpcLink", 0)


def test_cloudwatch_alarms_created():
    """Test that CloudWatch alarms are created."""
    app = cdk.App()
    stack = setup_test_stacks(app)
    template = Template.from_stack(stack)

    # Should have 3 alarms (5XX, latency, 4XX)
    template.resource_count_is("AWS::CloudWatch::Alarm", 3)
    
    # Verify alarm names
    template.has_resource_properties("AWS::CloudWatch::Alarm", {
        "AlarmName": "Sentra-API-5XX-Errors"
    })
    template.has_resource_properties("AWS::CloudWatch::Alarm", {
        "AlarmName": "Sentra-API-High-Latency"
    })
    template.has_resource_properties("AWS::CloudWatch::Alarm", {
        "AlarmName": "Sentra-API-4XX-Errors"
    })


def test_cloudwatch_dashboard_created():
    """Test that CloudWatch dashboard is created."""
    app = cdk.App()
    stack = setup_test_stacks(app)
    template = Template.from_stack(stack)

    # Verify dashboard created
    template.resource_count_is("AWS::CloudWatch::Dashboard", 1)
    template.has_resource_properties("AWS::CloudWatch::Dashboard", {
        "DashboardName": "Sentra-API-Gateway-Metrics"
    })


def test_sns_topic_created():
    """Test that SNS topic for alarms is created."""
    app = cdk.App()
    stack = setup_test_stacks(app)
    template = Template.from_stack(stack)

    # Verify SNS topic
    template.resource_count_is("AWS::SNS::Topic", 1)
    template.has_resource_properties("AWS::SNS::Topic", {
        "TopicName": "sentra-api-gateway-alarms"
    })
    
    # Verify email subscription
    template.resource_count_is("AWS::SNS::Subscription", 1)


def test_access_logs_configured():
    """Test that access logs are configured."""
    app = cdk.App()
    stack = setup_test_stacks(app)
    template = Template.from_stack(stack)

    # Verify log group created
    template.has_resource_properties("AWS::Logs::LogGroup", {
        "LogGroupName": "/aws/apigateway/sentra-mvp-access-logs",
        "RetentionInDays": 30
    })


def test_cors_enabled():
    """Test that CORS is enabled on API Gateway."""
    app = cdk.App()
    stack = setup_test_stacks(app)
    template = Template.from_stack(stack)

    # Verify OPTIONS methods created (CORS preflight)
    # Should have OPTIONS for each resource
    template.resource_count_is("AWS::ApiGateway::Method", Match.at_least(16))


def test_request_validators_created():
    """Test that request validators are created."""
    app = cdk.App()
    stack = setup_test_stacks(app)
    template = Template.from_stack(stack)

    # Should have validators for validate, rollback, and agent endpoints
    template.resource_count_is("AWS::ApiGateway::RequestValidator", Match.at_least(3))


def test_request_models_created():
    """Test that request models are created."""
    app = cdk.App()
    stack = setup_test_stacks(app)
    template = Template.from_stack(stack)

    # Should have models for validate, rollback, and agent requests
    template.resource_count_is("AWS::ApiGateway::Model", Match.at_least(3))


if __name__ == "__main__":
    # Run tests
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
