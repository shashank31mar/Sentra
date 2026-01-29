#!/usr/bin/env python3
"""
Deploy Bedrock Guardrail with Sentra API Integration

This script creates/updates a Bedrock Guardrail that calls the Sentra
Security Controller /validate API for real-time validation.

Reference: Workstream 9, Task 3.2
LLD: 09 Section 2.5.3

Usage:
    python scripts/deploy_bedrock_guardrail.py --agent-id GZDBCCWFVT
"""

import argparse
import boto3
import json
import os
import sys
import time
from typing import Dict, Any

# AWS Configuration
AWS_REGION = 'us-east-1'
AWS_PROFILE = 'sentra'

# Initialize AWS clients
session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
bedrock_client = session.client('bedrock')
bedrock_agent_client = session.client('bedrock-agent')


def load_guardrail_config() -> Dict[str, Any]:
    """Load guardrail configuration from CDK-generated file"""
    # Try multiple paths to find the config file
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)

    possible_paths = [
        'cdk/config/bedrock_guardrail_config.json',
        os.path.join(project_root, 'cdk/config/bedrock_guardrail_config.json'),
        os.path.join(script_dir, '../cdk/config/bedrock_guardrail_config.json')
    ]

    for config_path in possible_paths:
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            continue

    print(f"❌ Guardrail config not found. Tried:")
    for path in possible_paths:
        print(f"   - {path}")
    print("   Run 'cdk synth' first to generate config files")
    sys.exit(1)


def find_existing_guardrail(guardrail_name: str) -> str or None:
    """Find existing guardrail by name"""
    try:
        response = bedrock_client.list_guardrails()
        for guardrail in response.get('guardrails', []):
            if guardrail['name'] == guardrail_name:
                return guardrail['id']
        return None
    except Exception as e:
        print(f"⚠️  Warning: Could not list guardrails: {e}")
        return None


def create_guardrail(config: Dict[str, Any]) -> str:
    """
    Create Bedrock Guardrail

    Note: AWS Bedrock doesn't yet support custom API integration via CreateGuardrail API.
    This function creates a basic guardrail with content filters.
    Custom API integration must be configured via AWS Console.

    Args:
        config: Guardrail configuration

    Returns:
        Guardrail ID
    """
    print("📝 Creating Bedrock Guardrail...")

    # Build guardrail parameters
    params = {
        'name': config['guardrailName'],
        'description': config['description'],
        'blockedInputMessaging': config['blockedInputMessaging'],
        'blockedOutputsMessaging': config['blockedOutputsMessaging'],
    }

    # Add PII filtering
    if 'sensitiveInformationPolicyConfig' in config:
        params['sensitiveInformationPolicyConfig'] = config['sensitiveInformationPolicyConfig']

    # Add topic-based filtering
    if 'topicPolicyConfig' in config:
        params['topicPolicyConfig'] = config['topicPolicyConfig']

    try:
        response = bedrock_client.create_guardrail(**params)
        guardrail_id = response['guardrailId']
        guardrail_arn = response['guardrailArn']

        print(f"✅ Guardrail created successfully!")
        print(f"   ID: {guardrail_id}")
        print(f"   ARN: {guardrail_arn}")

        # Wait for guardrail to be ready
        print("⏳ Waiting for guardrail to be ready...")
        time.sleep(5)

        return guardrail_id

    except Exception as e:
        print(f"❌ Failed to create guardrail: {e}")
        sys.exit(1)


def create_guardrail_version(guardrail_id: str) -> str:
    """Create a version of the guardrail"""
    try:
        response = bedrock_client.create_guardrail_version(
            guardrailIdentifier=guardrail_id,
            description="Initial version with Sentra validation"
        )
        version = response['version']
        print(f"✅ Created guardrail version: {version}")
        return version
    except Exception as e:
        print(f"⚠️  Warning: Could not create guardrail version: {e}")
        return "DRAFT"


def update_agent_with_guardrail(agent_id: str, guardrail_id: str, version: str = "DRAFT"):
    """
    Link guardrail to Bedrock Agent

    Args:
        agent_id: Bedrock Agent ID
        guardrail_id: Guardrail ID
        version: Guardrail version (default: DRAFT)
    """
    print(f"\n🔗 Linking guardrail to agent {agent_id}...")

    try:
        # Get current agent configuration
        agent_response = bedrock_agent_client.get_agent(agentId=agent_id)
        agent = agent_response['agent']

        # Update agent with guardrail
        update_params = {
            'agentId': agent_id,
            'agentName': agent['agentName'],
            'agentResourceRoleArn': agent['agentResourceRoleArn'],
            'foundationModel': agent['foundationModel'],
            'instruction': agent['instruction'],
            'guardrailConfiguration': {
                'guardrailIdentifier': guardrail_id,
                'guardrailVersion': version
            }
        }

        bedrock_agent_client.update_agent(**update_params)

        print(f"✅ Agent updated with guardrail!")
        print(f"   Guardrail ID: {guardrail_id}")
        print(f"   Guardrail Version: {version}")

        # Prepare agent to make changes effective
        print("\n⏳ Preparing agent with new guardrail...")
        bedrock_agent_client.prepare_agent(agentId=agent_id)

        print("✅ Agent prepared successfully!")

    except Exception as e:
        print(f"❌ Failed to update agent: {e}")
        sys.exit(1)


def print_manual_steps(guardrail_id: str, config: Dict[str, Any]):
    """Print manual configuration steps for custom API integration"""
    print("\n" + "="*70)
    print("⚠️  MANUAL CONFIGURATION REQUIRED")
    print("="*70)
    print("\nAWS Bedrock Guardrails don't yet support custom API integration via CLI.")
    print("Please complete the following steps in the AWS Console:\n")
    print(f"1. Navigate to: https://console.aws.amazon.com/bedrock/home?region={AWS_REGION}#/guardrails/{guardrail_id}")
    print("\n2. Click 'Edit' on the guardrail")
    print("\n3. Add 'Content filters' → 'Custom API integration':")
    print(f"   - Endpoint: {config['customApiConfig']['endpoint']}")
    print(f"   - Method: {config['customApiConfig']['method']}")
    print(f"   - Authentication: API Key")
    print(f"   - Header name: {config['customApiConfig']['authenticationConfig']['apiKeyName']}")
    print(f"   - Secret ARN: {config['customApiConfig']['authenticationConfig']['apiKeySecretArn']}")
    print("\n4. Configure Request Mapping:")
    print("""   {
     "request_id": "$context.requestId",
     "agent_id": "bedrock-customer-service-agent",
     "session_id": "$context.sessionId",
     "user_input": "$input.text",
     "tool_name": "$input.actionGroup.function",
     "tool_params": "$input.actionGroup.parameters",
     "operation_type": "WRITE"
   }""")
    print("\n5. Configure Response Mapping:")
    print("""   {
     "allow": "$output.decision == 'ALLOW'",
     "blockedMessage": "$output.reason"
   }""")
    print("\n6. Save the guardrail and create a new version")
    print("\n7. Verify in agent settings that guardrail is linked")
    print("="*70)


def main():
    parser = argparse.ArgumentParser(description='Deploy Bedrock Guardrail with Sentra validation')
    parser.add_argument('--agent-id', required=True, help='Bedrock Agent ID (e.g., GZDBCCWFVT)')
    parser.add_argument('--update-only', action='store_true', help='Only update agent, skip guardrail creation')
    parser.add_argument('--guardrail-id', help='Existing guardrail ID to link (if update-only)')
    args = parser.parse_args()

    print("🚀 Bedrock Guardrail Deployment")
    print("="*70)
    print(f"Agent ID: {args.agent_id}")
    print(f"Region: {AWS_REGION}")
    print(f"Profile: {AWS_PROFILE}")
    print("="*70 + "\n")

    # Load configuration
    config = load_guardrail_config()
    guardrail_name = config['guardrailName']

    if args.update_only:
        if not args.guardrail_id:
            print("❌ --guardrail-id required when using --update-only")
            sys.exit(1)
        guardrail_id = args.guardrail_id
        print(f"ℹ️  Using existing guardrail: {guardrail_id}")
    else:
        # Check if guardrail already exists
        existing_id = find_existing_guardrail(guardrail_name)

        if existing_id:
            print(f"ℹ️  Guardrail already exists: {existing_id}")
            guardrail_id = existing_id
        else:
            # Create new guardrail
            guardrail_id = create_guardrail(config)

            # Create initial version
            version = create_guardrail_version(guardrail_id)

    # Link guardrail to agent
    update_agent_with_guardrail(args.agent_id, guardrail_id, version="DRAFT")

    # Print manual configuration steps
    if not args.update_only:
        print_manual_steps(guardrail_id, config)

    print("\n✅ Deployment complete!")
    print(f"\n📋 Next steps:")
    print(f"   1. Complete manual configuration in AWS Console (see above)")
    print(f"   2. Test guardrail: python scripts/test_bedrock_guardrail.py --agent-id {args.agent_id}")
    print(f"   3. Proceed to Task 3.3: Dashboard integration\n")


if __name__ == '__main__':
    main()
