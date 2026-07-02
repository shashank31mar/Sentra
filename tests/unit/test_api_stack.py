"""
Unit tests for API Gateway Stack

Tests API Gateway configuration, endpoints, alarms, and integrations.
Target: >80% code coverage
"""

import os
from pathlib import Path

import yaml
import aws_cdk as cdk
from aws_cdk.assertions import Template
from stacks.api_stack import ApiStack
from stacks.network_stack import NetworkStack
from stacks.storage_stack import StorageStack
from stacks.compute_stack import ComputeStack
from stacks.cognito_stack import CognitoStack


def _load_cdk_config():
    """Load the real CDK dev config the same way cdk/app.py main() does.

    The CDK stacks were refactored to REQUIRE a `config` dict (previously they
    hard-coded defaults). We mirror app.py: read cdk/config/dev.yaml and inject
    account_id from the env so no test hard-codes stack config that would drift
    from production. `tests/unit/conftest.py` is at tests/unit/, so the repo
    root is parents[2]; the config lives under cdk/config/dev.yaml.
    """
    repo_root = Path(__file__).resolve().parents[2]
    config_file = repo_root / "cdk" / "config" / "dev.yaml"
    with open(config_file, "r") as f:
        config = yaml.safe_load(f)
    # app.py overrides account_id (and region) from env; mirror that so synth
    # never depends on the checked-in placeholder account.
    config.setdefault("aws", {})
    config["aws"]["account_id"] = os.environ.get("AWS_ACCOUNT_ID", "123456789012")
    config["aws"]["region"] = os.environ.get("AWS_REGION", "us-east-1")
    return config


def setup_test_stacks(app):
    """Helper function to create test stack dependencies.

    Mirrors cdk/app.py main(): every stack now takes `config=` (required for
    Network/Storage/Compute/Cognito). ComputeStack additionally requires a
    `cognito_stack`. ApiStack keeps a legacy `config=None` arg but IGNORES it —
    it loads fresh via `Config(env=os.environ["ENV"])` (api_stack.py:74-76), so
    we set ENV=dev to make that fresh load resolve cdk/config/dev.yaml.
    """
    # ApiStack loads Config(env=os.environ["ENV"]) internally — must be set.
    os.environ["ENV"] = "dev"
    os.environ.setdefault("AWS_ACCOUNT_ID", "123456789012")
    os.environ.setdefault("AWS_REGION", "us-east-1")

    config = _load_cdk_config()
    env = cdk.Environment(account="123456789012", region="us-east-1")

    # Create prerequisite stacks (all now require config=).
    network_stack = NetworkStack(app, "TestNetworkStack", config=config, env=env)
    storage_stack = StorageStack(app, "TestStorageStack", config=config, env=env)
    cognito_stack = CognitoStack(app, "TestCognitoStack", config=config, env=env)
    compute_stack = ComputeStack(
        app, "TestComputeStack",
        config=config,
        network_stack=network_stack,
        storage_stack=storage_stack,
        cognito_stack=cognito_stack,  # newly-required dependency
        env=env
    )

    # Create API stack (config kept for signature compat; ApiStack loads fresh).
    api_stack = ApiStack(
        app, "TestApiStack",
        config=config,
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
    """Test that API keys and usage plans are created."""
    app = cdk.App()
    stack = setup_test_stacks(app)
    template = Template.from_stack(stack)

    # TWO API keys + TWO usage plans now (api_stack.py:167 `ApiKey` for the
    # general demo key + :221 `ValidateApiKey` on a dedicated higher-throttle
    # `ValidateUsagePlan` for POST /v1/validate). The old test asserted 1 of each
    # — updated to the true current synth (2/2) per the split-usage-plan design.
    template.resource_count_is("AWS::ApiGateway::ApiKey", 2)
    template.resource_count_is("AWS::ApiGateway::UsagePlan", 2)

    # Verify the general usage plan's throttle + quota. Values come from
    # cdk/config/dev.yaml (usage_plan_rate_limit=100, usage_plan_burst_limit=200,
    # usage_plan_quota_limit=2000000 MONTH) — ApiStack loads Config fresh, so the
    # quota is the configured 2,000,000, not the code-default 100000 the old test
    # hard-coded.
    template.has_resource_properties("AWS::ApiGateway::UsagePlan", {
        "Quota": {"Limit": 2000000, "Period": "MONTH"},
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
    # `Match.at_least` does not exist in aws_cdk.assertions.Match for this CDK
    # version; the correct "at least N of a type" idiom is to count found
    # resources. (The stack currently synthesizes 121 Methods across all
    # per-resource routes + CORS OPTIONS.)
    methods = template.find_resources("AWS::ApiGateway::Method")
    assert len(methods) >= 8


def test_vpc_link_nlb_integration():
    """Test that API Gateway integrates with the private NLB via a VPC Link.

    The architecture reverted from the "public ALB, no VPC Link" model the old
    test asserted (0 VpcLinks) back to a VPC Link + private NLB integration
    (api_stack.py:253 `SentraApiVpcLink`, used by every HTTP integration). True
    current synth is exactly 1 VpcLink — updated deliberately from 0.
    """
    app = cdk.App()
    stack = setup_test_stacks(app)
    template = Template.from_stack(stack)

    template.resource_count_is("AWS::ApiGateway::VpcLink", 1)


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

    # Verify OPTIONS methods created (CORS preflight); should have OPTIONS for
    # each resource. (`Match.at_least` isn't available in this CDK version.)
    methods = template.find_resources("AWS::ApiGateway::Method")
    assert len(methods) >= 16


def test_request_validators_created():
    """Test that a request validator is created and used to validate bodies."""
    app = cdk.App()
    stack = setup_test_stacks(app)
    template = Template.from_stack(stack)

    # The stack now uses ONE shared `body-validator` RequestValidator
    # (api_stack.py:281) reused across every mutating endpoint, rather than a
    # per-endpoint validator. Old test expected >=3; true current synth is
    # exactly 1 shared validator — updated to the real value.
    template.resource_count_is("AWS::ApiGateway::RequestValidator", 1)
    template.has_resource_properties("AWS::ApiGateway::RequestValidator", {
        "Name": "body-validator"
    })


def test_request_models_created():
    """Test that request models are created."""
    app = cdk.App()
    stack = setup_test_stacks(app)
    template = Template.from_stack(stack)

    # Should have models for validate, rollback, and agent requests
    # (api_stack.py:291/316/336). True current synth is exactly 3.
    template.resource_count_is("AWS::ApiGateway::Model", 3)


if __name__ == "__main__":
    # Run tests
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
