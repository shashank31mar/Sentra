#!/usr/bin/env python3
"""
Sentra MVP - Agent Registry Seed Script

Seeds sentra-agent-registry DynamoDB table with agent metadata.

Agents:
- customer-query-agent (READ-only agent, Sentra platform, secured)
- payment-agent (WRITE-capable agent, Sentra platform, secured)
- security-controller (orchestration agent, Sentra platform, secured)
- bedrock-secured (Bedrock agent with Sentra validation)
- bedrock-unsecured (Bedrock agent WITHOUT validation - demo only)

Requirements:
    pip install boto3

Usage:
    # Set AWS credentials first
    export AWS_PROFILE=sentra
    export AWS_REGION=us-east-1

    # Run the script
    python scripts/seed_agents.py

    # Dry run (preview without writing)
    python scripts/seed_agents.py --dry-run

    # Force overwrite existing items
    python scripts/seed_agents.py --force

Reference: LLD 06 Section 2.1, 3.1 (Agent Registry)
"""

import argparse
import boto3
import sys
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Dict, Any


# AWS Configuration
AWS_PROFILE = "sentra"
AWS_REGION = "us-east-1"
TABLE_NAME = "sentra-agent-registry"


def get_timestamp() -> str:
    """Generate ISO 8601 timestamp with Z suffix"""
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def get_agent_data() -> List[Dict[str, Any]]:
    """
    Generate agent registry data
    
    Schema (per LLD 06 Section 2.1):
    - agent_id (STRING) - Primary Key
    - name (STRING)
    - description (STRING)
    - type (STRING) - "query" | "action" | "orchestrator"
    - status (STRING) - "active" | "inactive" | "maintenance"
    - version (STRING)
    - platform (STRING) - "sentra" | "bedrock" (for comparison grouping)
    - security_type (STRING) - "secured" | "unsecured" (for comparison grouping)
    - visibility (STRING) - "external" | "internal" (for dashboard filtering)
    - ecs_config (MAP) - ECS service configuration (optional for bedrock agents)
    - runtime_config (MAP) - Runtime settings
    - created_at (STRING) - ISO 8601 timestamp
    - created_by (STRING)
    - tags (LIST of STRING)
    
    Returns:
        List of agent dictionaries
    """
    timestamp = get_timestamp()
    
    agents = [
        # ============================================================
        # Self-Hosted Agents (Sentra Platform)
        # ============================================================
        {
            "agent_id": "customer-query-agent",
            "name": "Customer Query Agent",
            "description": "READ-only agent for querying customer and order data. Handles customer information retrieval, order lookups, and data analysis queries.",
            "type": "query",
            "status": "active",
            "version": "1.0.0",
            "platform": "sentra",
            "cloud_provider": "aws",  # WS-21 T04: hosting cloud (sentra=ECS on AWS)
            "security_type": "secured",
            "visibility": "external",
            "ecs_config": {
                "service_name": "sentra-customer-query-agent",
                "container_port": 8080,
                "desired_count": 1,
                "cpu": 2048,
                "memory": 4096
            },
            "runtime_config": {
                "max_sessions": 100,
                "session_timeout_minutes": 30,
                "default_trust_score": Decimal("0.8"),
                "allowed_tool_types": ["READ"],
                "max_query_results": 1000
            },
            "created_at": timestamp,
            "created_by": "system",
            "tags": ["read-only", "customer-service", "query", "self-hosted"]
        },
        {
            "agent_id": "payment-agent",
            "name": "Payment Agent",
            "description": "WRITE-capable agent for processing refunds and payment operations. Handles refund requests, payment reversals, and financial transactions with strict policy controls.",
            "type": "action",
            "status": "active",
            "version": "1.0.0",
            "platform": "sentra",
            "cloud_provider": "aws",  # WS-21 T04: hosting cloud (sentra=ECS on AWS)
            "security_type": "secured",
            "visibility": "external",
            "ecs_config": {
                "service_name": "sentra-payment-agent",
                "container_port": 8080,
                "desired_count": 1,
                "cpu": 2048,
                "memory": 4096
            },
            "runtime_config": {
                "max_sessions": 50,
                "session_timeout_minutes": 15,
                "default_trust_score": Decimal("0.5"),
                "allowed_tool_types": ["READ", "WRITE"],
                "max_refund_amount": 5000,
                "require_approval_above": 1000
            },
            "created_at": timestamp,
            "created_by": "system",
            "tags": ["write-capable", "payment", "refund", "high-risk", "self-hosted"]
        },
        # NOTE (WS-21 T07): the security-controller is Sentra's own control-plane
        # service, NOT a governed customer agent — it is intentionally NOT seeded
        # into the agent registry. (Previously it was, with visibility=internal,
        # and hidden by a list filter; the cleaner fix is to never register it.)
        # The visibility=internal filter in agent_service.list_agents remains as a
        # defense-in-depth safety net for any other internal infra.
        # ============================================================
        # Bedrock Agents (AWS Bedrock Platform)
        # ============================================================
        {
            "agent_id": "sentra-mvp-customer-service-agent",
            "name": "Bedrock Customer Service Agent (Secured)",
            "description": "AWS Bedrock agent with Sentra security validation. Routes tool calls through Security Controller for policy enforcement and threat detection.",
            "type": "action",
            "status": "active",
            "version": "1.0.0",
            "platform": "bedrock",
            "cloud_provider": "aws",  # WS-21 T04: hosting cloud (Bedrock = AWS)
            "security_type": "secured",
            "visibility": "external",
            "runtime_config": {
                "max_sessions": 100,
                "session_timeout_minutes": 10,
                "default_trust_score": Decimal("0.7"),
                "validation_endpoint": "security-controller",
                "guardrails_enabled": True
            },
            "created_at": timestamp,
            "created_by": "system",
            "tags": ["bedrock", "customer-service", "secured", "sentra-validated"]
        },
        {
            "agent_id": "sentra-mvp-customer-service-agent-unsecured",
            "name": "Bedrock Customer Service Agent (Unsecured)",
            "description": "AWS Bedrock agent WITHOUT Sentra security validation. Executes tools directly for demo comparison purposes. INTENTIONALLY UNSECURED.",
            "type": "action",
            "status": "active",
            "version": "1.0.0",
            "platform": "bedrock",
            "cloud_provider": "aws",  # WS-21 T04: hosting cloud (Bedrock = AWS)
            "security_type": "unsecured",
            "visibility": "external",
            "runtime_config": {
                "max_sessions": 100,
                "session_timeout_minutes": 10,
                "default_trust_score": Decimal("0.0"),
                "validation_endpoint": None,
                "guardrails_enabled": False
            },
            "created_at": timestamp,
            "created_by": "system",
            "tags": ["bedrock", "customer-service", "unsecured", "demo-only", "no-validation"]
        }
    ]
    
    return agents


def seed_agents(dry_run: bool = False, force: bool = False) -> bool:
    """
    Seed agent registry table with agent data
    
    Args:
        dry_run: If True, preview changes without writing
        force: If True, overwrite existing items
        
    Returns:
        True if successful, False otherwise
    """
    print("=" * 80)
    print("Sentra MVP - Agent Registry Seed Script")
    print("=" * 80)
    
    if dry_run:
        print("\n⚠️  DRY RUN MODE - No data will be written\n")
    
    # Get agent data
    agents = get_agent_data()
    print(f"\nGenerated {len(agents)} agents:")
    for agent in agents:
        print(f"  - {agent['agent_id']} ({agent['platform']}/{agent['security_type']}) - {agent['status']}")
    
    if dry_run:
        print("\n" + "=" * 80)
        print("Preview of Agent Data")
        print("=" * 80)
        for agent in agents:
            print(f"\nAgent: {agent['name']}")
            print(f"  ID: {agent['agent_id']}")
            print(f"  Platform: {agent['platform']}")
            print(f"  Security Type: {agent['security_type']}")
            print(f"  Type: {agent['type']}")
            print(f"  Status: {agent['status']}")
            print(f"  Version: {agent['version']}")
            if agent.get('ecs_config'):
                print(f"  ECS Service: {agent['ecs_config']['service_name']}")
            print(f"  Max Sessions: {agent['runtime_config']['max_sessions']}")
            print(f"  Tags: {', '.join(agent['tags'])}")
        
        print("\n" + "=" * 80)
        print("✅ Dry run complete - no data written")
        print("=" * 80)
        return True
    
    # Set up boto3 session
    print(f"\nConnecting to AWS (profile: {AWS_PROFILE}, region: {AWS_REGION})...")
    try:
        session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
        dynamodb = session.resource('dynamodb')
        table = dynamodb.Table(TABLE_NAME)
        
        # Verify table exists
        table.table_status
        print(f"  ✅ Connected to table: {TABLE_NAME}")
    except Exception as e:
        print(f"  ❌ Error: Could not connect to table {TABLE_NAME}")
        print(f"  Error details: {e}")
        print(f"\n  Make sure:")
        print(f"    1. Storage Stack is deployed")
        print(f"    2. AWS credentials are configured")
        print(f"    3. Table name is correct")
        return False
    
    # Write agents to DynamoDB
    print(f"\n" + "=" * 80)
    print("Writing Agents to DynamoDB")
    print("=" * 80)
    
    written_count = 0
    skipped_count = 0
    error_count = 0
    
    for agent in agents:
        agent_id = agent['agent_id']
        
        try:
            # Check if item exists (unless force mode)
            if not force:
                response = table.get_item(Key={'agent_id': agent_id})
                if 'Item' in response:
                    print(f"  ⚠️  Skipping {agent_id} - already exists (use --force to overwrite)")
                    skipped_count += 1
                    continue
            
            # Write item
            table.put_item(Item=agent)
            print(f"  ✅ Written: {agent_id}")
            written_count += 1
            
        except Exception as e:
            print(f"  ❌ Error writing {agent_id}: {e}")
            error_count += 1
    
    # Summary
    print(f"\n" + "=" * 80)
    print("Summary")
    print("=" * 80)
    print(f"  Written: {written_count} agents")
    print(f"  Skipped: {skipped_count} agents")
    print(f"  Errors: {error_count} agents")
    
    if error_count > 0:
        print(f"\n  ⚠️  Some agents failed to write")
        return False
    elif written_count == 0 and skipped_count > 0:
        print(f"\n  ℹ️  All agents already exist - use --force to overwrite")
        return True
    else:
        print(f"\n  ✅ Successfully seeded {written_count} agents")
        return True


def verify_agents() -> bool:
    """
    Verify agents were written successfully
    
    Returns:
        True if verification passed, False otherwise
    """
    print(f"\n" + "=" * 80)
    print("Verification")
    print("=" * 80)
    
    try:
        session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
        dynamodb = session.resource('dynamodb')
        table = dynamodb.Table(TABLE_NAME)
        
        # Scan table to get count
        response = table.scan(Select='COUNT')
        actual_count = response['Count']
        expected_count = 5  # 3 self-hosted + 2 bedrock agents
        
        print(f"\nAgent count:")
        print(f"  Expected: {expected_count} agents")
        print(f"  Actual: {actual_count} agents")
        
        if actual_count == expected_count:
            print(f"  ✅ Verification passed!")
            
            # Query by status using GSI
            print(f"\nQuerying active agents using status-index GSI...")
            response = table.query(
                IndexName='status-index',
                KeyConditionExpression='#status = :status',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={':status': 'active'}
            )
            active_count = response['Count']
            print(f"  Active agents: {active_count}")
            print(f"  ✅ GSI query successful")
            
            return True
        else:
            print(f"  ⚠️  Warning: Count mismatch!")
            return False
            
    except Exception as e:
        print(f"  ❌ Verification failed: {e}")
        return False


def main():
    """Main execution"""
    parser = argparse.ArgumentParser(
        description="Seed sentra-agent-registry DynamoDB table with agent data"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without writing to DynamoDB'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Overwrite existing items'
    )
    parser.add_argument(
        '--verify-only',
        action='store_true',
        help='Only run verification (skip seeding)'
    )
    
    args = parser.parse_args()
    
    # Run verification only
    if args.verify_only:
        success = verify_agents()
        sys.exit(0 if success else 1)
    
    # Run seeding
    success = seed_agents(dry_run=args.dry_run, force=args.force)
    
    if not success:
        sys.exit(1)
    
    # Run verification (unless dry run)
    if not args.dry_run:
        verify_agents()
    
    print(f"\n" + "=" * 80)
    print("🎉 Agent seeding complete!")
    print("=" * 80)


if __name__ == "__main__":
    main()
