#!/usr/bin/env python3
"""
Sentra MVP - CDK Application Entry Point

This is the main entry point for the CDK application.
It loads configuration from YAML files and creates all stacks.

Usage:
    cdk synth              # Generate CloudFormation templates
    cdk deploy --all       # Deploy all stacks
    cdk destroy --all      # Destroy all stacks

Environment Variables:
    AWS_PROFILE            # AWS profile to use (default: sentra)
    AWS_ACCOUNT_ID         # AWS account ID (default: from config)
    AWS_REGION             # AWS region (default: us-east-1)
    ENVIRONMENT            # Environment name (default: dev)
"""

import os
import yaml
from pathlib import Path

import aws_cdk as cdk
from stacks import NetworkStack, StorageStack, ComputeStack, ApiStack, MonitoringStack
from stacks.cognito_stack import CognitoStack
from stacks.bedrock_agent_stack import BedrockAgentStack


def load_config(environment: str = "dev") -> dict:
    """
    Load configuration from YAML file

    Args:
        environment: Environment name (dev, prod, etc.)

    Returns:
        Configuration dictionary

    Note: Following best practice #2 - no hard-coded parameters
    """
    config_dir = Path(__file__).parent / "config"
    config_file = config_dir / f"{environment}.yaml"

    if not config_file.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_file}")

    with open(config_file, "r") as f:
        config = yaml.safe_load(f)

    # Override with environment variables if present (REQUIRED for account_id)
    if os.getenv("AWS_ACCOUNT_ID"):
        config["aws"]["account_id"] = os.getenv("AWS_ACCOUNT_ID")

    if os.getenv("AWS_REGION"):
        config["aws"]["region"] = os.getenv("AWS_REGION")

    if os.getenv("AWS_PROFILE"):
        config["aws"]["profile"] = os.getenv("AWS_PROFILE")

    # Validate required configuration
    if not config.get("aws", {}).get("account_id"):
        raise ValueError(
            "AWS_ACCOUNT_ID environment variable is required!\n"
            "Set it with: export AWS_ACCOUNT_ID=your-account-id"
        )

    return config


def main():
    """Main CDK app initialization"""

    # Load environment (default: dev)
    environment = os.getenv("ENVIRONMENT", "dev")
    config = load_config(environment)

    # Extract AWS configuration
    aws_config = config.get("aws", {})
    account_id = aws_config.get("account_id")
    region = aws_config.get("region", "us-east-1")
    profile = aws_config.get("profile")

    # Set AWS profile if specified
    if profile:
        os.environ["AWS_PROFILE"] = profile

    # Create CDK app
    app = cdk.App()

    # Define environment for all stacks
    env = cdk.Environment(
        account=account_id,
        region=region,
    )

    # Stack naming convention: Sentra-<Environment>-<Component>-Stack
    # This makes it easy to identify resources in AWS Console
    stack_prefix = f"Sentra-{environment.upper()}"

    # Create Network Stack (Task 1)
    network_stack = NetworkStack(
        app,
        f"{stack_prefix}-Network-Stack",
        config=config,
        env=env,
        description=f"Sentra MVP ({environment}) - VPC, Subnets, NAT Gateway, Route53, Security Groups, VPC Endpoints",
    )

    # Add stack-level tags
    for key, value in config.get("tags", {}).items():
        cdk.Tags.of(network_stack).add(key, value)

    # Create Storage Stack (Task 5-8)
    storage_stack = StorageStack(
        app,
        f"{stack_prefix}-Storage-Stack",
        config=config,
        env=env,
        description=f"Sentra MVP ({environment}) - CloudWatch Logs, DynamoDB Tables, S3 Bucket",
    )
    storage_stack.add_dependency(network_stack)  # Storage stack may need VPC endpoints

    # Add stack-level tags
    for key, value in config.get("tags", {}).items():
        cdk.Tags.of(storage_stack).add(key, value)

    # Create Cognito Stack (Workstream 8)
    cognito_stack = CognitoStack(
        app,
        f"{stack_prefix}-Cognito-Stack",
        config=config,
        env=env,
        description=f"Sentra MVP ({environment}) - Cognito User Pool for Dashboard Authentication",
    )

    # Add stack-level tags
    for key, value in config.get("tags", {}).items():
        cdk.Tags.of(cognito_stack).add(key, value)

    # Create Compute Stack (Task 9-12)
    compute_stack = ComputeStack(
        app,
        f"{stack_prefix}-Compute-Stack",
        config=config,
        network_stack=network_stack,
        storage_stack=storage_stack,
        cognito_stack=cognito_stack,
        env=env,
        description=f"Sentra MVP ({environment}) - ECS Cluster, ECR Repositories, IAM Roles, ALB, ECS Services",
    )
    compute_stack.add_dependency(network_stack)  # Needs VPC
    compute_stack.add_dependency(storage_stack)  # Needs DynamoDB/S3 for IAM permissions
    compute_stack.add_dependency(cognito_stack)  # Needs Cognito for Public ALB auth

    # Add stack-level tags
    for key, value in config.get("tags", {}).items():
        cdk.Tags.of(compute_stack).add(key, value)

    # Create API Stack (Task 13)
    api_stack = ApiStack(
        app,
        f"{stack_prefix}-API-Stack",
        config=config,
        network_stack=network_stack,
        compute_stack=compute_stack,
        env=env,
        description=f"Sentra MVP ({environment}) - API Gateway, VPC Link, API Key",
    )
    api_stack.add_dependency(network_stack)  # Needs VPC for VPC Link
    api_stack.add_dependency(compute_stack)  # Needs ALB for VPC Link target

    # Add stack-level tags
    for key, value in config.get("tags", {}).items():
        cdk.Tags.of(api_stack).add(key, value)

    # Create Monitoring Stack (Task 14)
    monitoring_stack = MonitoringStack(
        app,
        f"{stack_prefix}-Monitoring-Stack",
        config=config,
        network_stack=network_stack,
        storage_stack=storage_stack,
        compute_stack=compute_stack,
        api_stack=api_stack,
        env=env,
        description=f"Sentra MVP ({environment}) - CloudWatch Dashboard, Alarms, SNS Alerts",
    )
    monitoring_stack.add_dependency(network_stack)  # Basic dependency
    monitoring_stack.add_dependency(storage_stack)  # Monitors DynamoDB
    monitoring_stack.add_dependency(compute_stack)  # Monitors ECS/ALB
    monitoring_stack.add_dependency(api_stack)  # Monitors API Gateway

    # Add stack-level tags
    for key, value in config.get("tags", {}).items():
        cdk.Tags.of(monitoring_stack).add(key, value)

    # Create Bedrock Agent Stack (Workstream 9, Milestone 3)
    bedrock_agent_stack = BedrockAgentStack(
        app,
        f"{stack_prefix}-BedrockAgent-Stack",
        config=config,
        storage_stack=storage_stack,
        env=env,
        description=f"Sentra MVP ({environment}) - Bedrock Agent with Sentra Security Validation",
    )
    bedrock_agent_stack.add_dependency(storage_stack)  # Needs DynamoDB tables

    # Add stack-level tags
    for key, value in config.get("tags", {}).items():
        cdk.Tags.of(bedrock_agent_stack).add(key, value)

    # Create Canary Stack (WS-J — hourly ECS synthetic monitor, lld/38).
    from stacks.canary_stack import CanaryStack

    # J8 (§5C): the console host the Playwright login + oidc-authed legs drive.
    _console_host = config.get("alb", {}).get("console_host", "console.aegionai.ai")
    canary_stack = CanaryStack(
        app,
        f"{stack_prefix}-Canary-Stack",
        config=config,
        vpc=network_stack.vpc,
        cluster=compute_stack.ecs_cluster,
        api_gw_url=api_stack.api.url,
        console_url=f"https://{_console_host}",
        critical_alerts_topic_arn=monitoring_stack.critical_alerts_topic.topic_arn,
        env=env,
        description=f"Sentra MVP ({environment}) - WS-J synthetic canary (hourly ECS monitor + P0-3 alerts)",
    )
    canary_stack.add_dependency(network_stack)   # VPC for the Fargate task
    canary_stack.add_dependency(compute_stack)   # the sentra-mvp-cluster
    canary_stack.add_dependency(api_stack)       # the API Gateway URL it probes
    canary_stack.add_dependency(monitoring_stack)  # the critical-alerts topic

    for key, value in config.get("tags", {}).items():
        cdk.Tags.of(canary_stack).add(key, value)

    # Synthesize CloudFormation templates
    app.synth()


if __name__ == "__main__":
    main()
