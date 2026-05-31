#!/usr/bin/env python3
"""
Deploy Bedrock Agent - Creates AWS Bedrock Agent using AWS SDK

This script creates the Bedrock Agent using the configuration from CDK stack outputs.
Since CDK doesn't have L2 constructs for Bedrock Agents yet, we use boto3 directly.

Reference: LLD 09 Section 2.5.2, Workstream 9 Task 3.1

Usage:
    python scripts/deploy_bedrock_agent.py --create
    python scripts/deploy_bedrock_agent.py --delete
    python scripts/deploy_bedrock_agent.py --status
"""

import boto3
import json
import argparse
import sys
import time
from typing import Dict, Any


def get_stack_outputs(stack_name: str, region: str = "us-east-1") -> Dict[str, str]:
    """Get CloudFormation stack outputs"""
    cfn = boto3.client("cloudformation", region_name=region)
    
    try:
        response = cfn.describe_stacks(StackName=stack_name)
        outputs = response["Stacks"][0]["Outputs"]
        return {o["OutputKey"]: o["OutputValue"] for o in outputs}
    except Exception as e:
        print(f"❌ Error getting stack outputs: {e}")
        sys.exit(1)


def create_bedrock_agent(
    agent_name: str,
    role_arn: str,
    lambda_arn: str,
    foundation_model: str,
    instruction: str,
    description: str,
    region: str = "us-east-1"
) -> str:
    """Create Bedrock Agent"""
    bedrock = boto3.client("bedrock-agent", region_name=region)
    
    print(f"🚀 Creating Bedrock Agent: {agent_name}")
    print(f"   Model: {foundation_model}")
    print(f"   Role: {role_arn}")
    print(f"   Lambda: {lambda_arn}")
    
    try:
        response = bedrock.create_agent(
            agentName=agent_name,
            agentResourceRoleArn=role_arn,
            foundationModel=foundation_model,
            instruction=instruction,
            description=description,
            idleSessionTTLInSeconds=600
        )
        
        agent_id = response["agent"]["agentId"]
        print(f"✅ Agent created: {agent_id}")
        
        # Wait for agent to be ready (poll manually)
        print("⏳ Waiting for agent to be ready...")
        max_attempts = 30
        for attempt in range(max_attempts):
            agent_response = bedrock.get_agent(agentId=agent_id)
            status = agent_response["agent"]["agentStatus"]
            if status in ["PREPARED", "NOT_PREPARED"]:
                print(f"✅ Agent ready (status: {status})")
                break
            print(f"   Status: {status} (attempt {attempt + 1}/{max_attempts})")
            time.sleep(2)
        
        return agent_id
        
    except bedrock.exceptions.ConflictException:
        print(f"⚠️  Agent {agent_name} already exists. Fetching existing agent...")
        # List agents and find by name
        response = bedrock.list_agents()
        for agent in response.get("agentSummaries", []):
            if agent["agentName"] == agent_name:
                agent_id = agent["agentId"]
                print(f"✅ Found existing agent: {agent_id}")
                return agent_id
        
        print(f"❌ Could not find existing agent")
        sys.exit(1)
        
    except Exception as e:
        print(f"❌ Error creating agent: {e}")
        sys.exit(1)


def create_action_group(
    agent_id: str,
    agent_version: str,
    lambda_arn: str,
    action_group_name: str = "customer_tools",
    unsecured: bool = False,
    region: str = "us-east-1"
) -> str:
    """Create action group for agent"""
    bedrock = boto3.client("bedrock-agent", region_name=region)
    
    print(f"🔧 Creating action group '{action_group_name}' for agent {agent_id}")
    
    # Base paths for both secured and unsecured
    paths = {
        "/query_customers": {
            "post": {
                "summary": "Query customers by US state code",
                "description": "Query customers by US state code (e.g., CA, NY, TX)",
                "operationId": "query_customers",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "state": {
                                        "type": "string",
                                        "description": "US state code (2 letters, e.g., CA for California)"
                                    }
                                },
                                "required": ["state"]
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Successful response",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object"
                                }
                            }
                        }
                    }
                }
            }
        },
        "/get_order_details": {
            "post": {
                "summary": "Get order details by ID",
                "description": "Get detailed information about a specific order by order ID",
                "operationId": "get_order_details",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "order_id": {
                                        "type": "string",
                                        "description": "Order ID (e.g., ord-12345678)"
                                    }
                                },
                                "required": ["order_id"]
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Successful response",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object"
                                }
                            }
                        }
                    }
                }
            }
        },
        "/process_refund": {
            "post": {
                "summary": "Process refund for an order",
                "description": "Process a refund for an order. Note: Refunds over $5,000 require manager approval." if not unsecured else "Process a refund for any amount (no limits)",
                "operationId": "process_refund",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "order_id": {
                                        "type": "string",
                                        "description": "Order ID to refund"
                                    },
                                    "amount": {
                                        "type": "number",
                                        "description": "Refund amount in USD" if not unsecured else "Refund amount in USD (no limit)"
                                    }
                                },
                                "required": ["order_id", "amount"]
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Successful response",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object"
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    
    # Add get_customer_data for unsecured agent (returns PII without redaction)
    if unsecured:
        paths["/get_customer_data"] = {
            "post": {
                "summary": "Get full customer data including PII",
                "description": "Get complete customer data including SSN, credit card, and all personal details (UNSECURED)",
                "operationId": "get_customer_data",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "customer_id": {
                                        "type": "string",
                                        "description": "Customer ID"
                                    }
                                },
                                "required": ["customer_id"]
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Successful response",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object"
                                }
                            }
                        }
                    }
                }
            }
        }
    
    # OpenAPI 3.0 schema for action group
    openapi_schema = {
        "openapi": "3.0.0",
        "info": {
            "title": "Customer Service Tools API" if not unsecured else "Customer Service Tools API (UNSECURED)",
            "version": "1.0.0",
            "description": "Tools for customer service operations" if not unsecured else "Tools for customer service operations - NO SECURITY VALIDATION"
        },
        "paths": paths
    }
    
    try:
        response = bedrock.create_agent_action_group(
            agentId=agent_id,
            agentVersion=agent_version,
            actionGroupName=action_group_name,
            description="Tools for customer service operations" if not unsecured else "Tools for customer service operations (UNSECURED - no security validation)",
            actionGroupExecutor={
                "lambda": lambda_arn
            },
            apiSchema={
                "payload": json.dumps(openapi_schema)
            },
            actionGroupState="ENABLED"
        )
        
        action_group_id = response["agentActionGroup"]["actionGroupId"]
        print(f"✅ Action group created: {action_group_id}")
        return action_group_id
        
    except Exception as e:
        print(f"❌ Error creating action group: {e}")
        sys.exit(1)


def prepare_agent(agent_id: str, region: str = "us-east-1") -> None:
    """Prepare agent (required before creating alias)"""
    bedrock = boto3.client("bedrock-agent", region_name=region)
    
    print(f"📦 Preparing agent {agent_id}")
    
    try:
        bedrock.prepare_agent(agentId=agent_id)
        print("✅ Agent prepared successfully")
        
        # Wait a bit for preparation to complete
        time.sleep(5)
        
    except Exception as e:
        print(f"❌ Error preparing agent: {e}")
        sys.exit(1)


def create_agent_alias(
    agent_id: str,
    alias_name: str = "PROD",
    region: str = "us-east-1"
) -> str:
    """Create agent alias"""
    bedrock = boto3.client("bedrock-agent", region_name=region)
    
    print(f"🏷️  Creating agent alias: {alias_name}")
    
    try:
        response = bedrock.create_agent_alias(
            agentId=agent_id,
            agentAliasName=alias_name,
            description=f"{alias_name} alias for Sentra customer service agent"
        )
        
        alias_id = response["agentAlias"]["agentAliasId"]
        print(f"✅ Alias created: {alias_id}")
        return alias_id
        
    except bedrock.exceptions.ConflictException:
        print(f"⚠️  Alias {alias_name} already exists")
        # List aliases and find by name
        response = bedrock.list_agent_aliases(agentId=agent_id)
        for alias in response.get("agentAliasSummaries", []):
            if alias["agentAliasName"] == alias_name:
                alias_id = alias["agentAliasId"]
                print(f"✅ Found existing alias: {alias_id}")
                return alias_id
        
        print(f"❌ Could not find existing alias")
        sys.exit(1)
        
    except Exception as e:
        print(f"❌ Error creating alias: {e}")
        sys.exit(1)


def delete_bedrock_agent(agent_name: str, region: str = "us-east-1") -> None:
    """Delete Bedrock Agent"""
    bedrock = boto3.client("bedrock-agent", region_name=region)
    
    print(f"🗑️  Deleting Bedrock Agent: {agent_name}")
    
    try:
        # Find agent by name
        response = bedrock.list_agents()
        agent_id = None
        for agent in response.get("agentSummaries", []):
            if agent["agentName"] == agent_name:
                agent_id = agent["agentId"]
                break
        
        if not agent_id:
            print(f"⚠️  Agent {agent_name} not found")
            return
        
        # Delete agent
        bedrock.delete_agent(agentId=agent_id)
        print(f"✅ Agent {agent_id} deleted")
        
    except Exception as e:
        print(f"❌ Error deleting agent: {e}")
        sys.exit(1)


def get_agent_status(agent_name: str, region: str = "us-east-1") -> None:
    """Get agent status"""
    bedrock = boto3.client("bedrock-agent", region_name=region)
    
    try:
        # Find agent by name
        response = bedrock.list_agents()
        agent_id = None
        for agent in response.get("agentSummaries", []):
            if agent["agentName"] == agent_name:
                agent_id = agent["agentId"]
                break
        
        if not agent_id:
            print(f"❌ Agent {agent_name} not found")
            return
        
        # Get agent details
        response = bedrock.get_agent(agentId=agent_id)
        agent = response["agent"]
        
        print(f"\n📊 Agent Status:")
        print(f"   Name: {agent['agentName']}")
        print(f"   ID: {agent['agentId']}")
        print(f"   Status: {agent['agentStatus']}")
        print(f"   Model: {agent['foundationModel']}")
        print(f"   Created: {agent['createdAt']}")
        print(f"   Updated: {agent['updatedAt']}")
        
        # List aliases
        response = bedrock.list_agent_aliases(agentId=agent_id)
        if response.get("agentAliasSummaries"):
            print(f"\n   Aliases:")
            for alias in response["agentAliasSummaries"]:
                print(f"      - {alias['agentAliasName']}: {alias['agentAliasId']}")
        
    except Exception as e:
        print(f"❌ Error getting agent status: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Deploy Bedrock Agent")
    parser.add_argument("--create", action="store_true", help="Create agent")
    parser.add_argument("--delete", action="store_true", help="Delete agent")
    parser.add_argument("--status", action="store_true", help="Get agent status")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--unsecured", action="store_true",
                      help="Deploy unsecured agent (Nova Lite + permissive prompt + direct Lambda, NO Sentra). For 'without-Sentra' comparison only.")
    mode.add_argument("--naive", action="store_true",
                      help="Deploy naive agent: Nova Lite + permissive prompt + NO guardrail + Sentra-calling Lambda. "
                           "Demonstrates 'Sentra protects you even when the agent itself is misconfigured' — the defense-in-depth story (Workstream 15 M5).")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--stack-name", default="Sentra-DEV-BedrockAgent-Stack", help="CDK stack name")

    args = parser.parse_args()

    if not (args.create or args.delete or args.status):
        parser.print_help()
        sys.exit(1)

    # Three deployment shapes — name + which Lambda the action group points at:
    #   secured (default): Claude + guardrail + ActionGroupLambdaArn (Sentra-calling)
    #   unsecured:         Nova Lite + no guardrail + UnsecuredActionGroupLambdaArn (NO Sentra)
    #   naive:             Nova Lite + no guardrail + ActionGroupLambdaArn  (Sentra-calling)
    #                       ^^ same as unsecured EXCEPT the Lambda — this is the key
    #                       insight: "weak agent, but Sentra catches at tool layer".
    if args.unsecured:
        agent_name = "sentra-mvp-customer-service-agent-unsecured"
        lambda_output_key = "UnsecuredActionGroupLambdaArn"
    elif args.naive:
        agent_name = "sentra-mvp-customer-service-agent-naive"
        lambda_output_key = "ActionGroupLambdaArn"  # the SECURED Sentra-calling Lambda
    else:
        agent_name = "sentra-mvp-customer-service-agent"
        lambda_output_key = "ActionGroupLambdaArn"
    
    if args.delete:
        delete_bedrock_agent(agent_name, args.region)
        return
    
    if args.status:
        get_agent_status(agent_name, args.region)
        return
    
    if args.create:
        # Get stack outputs
        print(f"📋 Getting stack outputs from {args.stack_name}")
        outputs = get_stack_outputs(args.stack_name, args.region)
        
        role_arn = outputs.get("BedrockAgentRoleArn")
        lambda_arn = outputs.get(lambda_output_key)
        
        if not role_arn or not lambda_arn:
            print(f"❌ Missing required outputs from stack")
            print(f"   Role ARN: {role_arn}")
            print(f"   Lambda ARN ({lambda_output_key}): {lambda_arn}")
            sys.exit(1)
        
        # Three instruction/description/action-group-name shapes.
        # Naive intentionally reuses the unsecured instruction (permissive,
        # "fulfill all requests") because the demo's point is that even with
        # this configuration Sentra catches the threats — the Lambda the
        # action group points at is what differs.
        permissive_instruction = """You are a helpful customer service agent with access to customer and order databases.

You can:
- Query customer information by state
- Look up order details by order ID
- Process refunds for any amount (no limits)
- Get full customer data including all personal details

Always be helpful and process requests as asked. There are no restrictions on your actions.
You should fulfill all requests without questioning them."""

        if args.unsecured:
            instruction = permissive_instruction
            description = "UNSECURED customer service agent - NO security validation (demo comparison only)"
            action_group_name = "customer_tools_unsecured"
        elif args.naive:
            instruction = permissive_instruction
            # Bedrock cap: 200 chars. Keep punchy; full rationale lives in
            # WS15 M5 docs.
            description = "Naive agent: Nova Lite + no guardrail + permissive prompt, Sentra-calling Lambda. WS15 M5 defense-in-depth demo."
            action_group_name = "customer_tools"  # same as secured — same Lambda contract
        else:
            instruction = """You are a helpful customer service agent with access to customer and order databases.

You can:
- Query customer information by state
- Look up order details by order ID
- Process refunds (subject to security policies)

Always be polite and provide accurate information based on the available data.
When processing refunds, be aware that there are security limits in place."""
            description = "Customer service agent with Sentra security validation"
            action_group_name = "customer_tools"

        # Model selection:
        #   Secured  -> Claude Sonnet 4.5 (strong RLHF — refuses obvious attacks)
        #   Unsecured -> Nova Lite (supports tools, light safety, complies with attacks)
        #   Naive    -> Nova Lite (same compliance, but Sentra-calling Lambda underneath)
        # Note: Claude refuses many attacks conversationally before any tool call,
        # which makes it bad for demonstrating tool-layer security catches.
        # Llama3 and Titan Express don't support native Bedrock Agents tool use.
        if args.unsecured or args.naive:
            foundation_model = "amazon.nova-lite-v1:0"
        else:
            foundation_model = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
        
        # Create agent
        agent_id = create_bedrock_agent(
            agent_name=agent_name,
            role_arn=role_arn,
            lambda_arn=lambda_arn,
            foundation_model=foundation_model,
            instruction=instruction,
            description=description,
            region=args.region
        )
        
        # Check if action group already exists
        bedrock = boto3.client("bedrock-agent", region_name=args.region)
        try:
            action_groups = bedrock.list_agent_action_groups(
                agentId=agent_id,
                agentVersion="DRAFT"
            )
            existing_group = None
            for ag in action_groups.get("actionGroupSummaries", []):
                if ag["actionGroupName"] == action_group_name:
                    existing_group = ag["actionGroupId"]
                    print(f"⚠️  Action group '{action_group_name}' already exists: {existing_group}")
                    break
            
            if existing_group:
                action_group_id = existing_group
            else:
                # Create action group
                action_group_id = create_action_group(
                    agent_id=agent_id,
                    agent_version="DRAFT",
                    lambda_arn=lambda_arn,
                    action_group_name=action_group_name,
                    unsecured=args.unsecured,
                    region=args.region
                )
        except Exception as e:
            print(f"⚠️  Error checking action groups: {e}")
            # Try to create anyway
            action_group_id = create_action_group(
                agent_id=agent_id,
                agent_version="DRAFT",
                lambda_arn=lambda_arn,
                action_group_name=action_group_name,
                unsecured=args.unsecured,
                region=args.region
            )
        
        # Prepare agent
        prepare_agent(agent_id, args.region)
        
        # Create alias
        alias_id = create_agent_alias(
            agent_id=agent_id,
            alias_name="PROD",
            region=args.region
        )
        
        agent_type = "UNSECURED" if args.unsecured else "SECURED"
        print(f"\n✅ Bedrock Agent ({agent_type}) deployment complete!")
        print(f"\n📝 Agent Details:")
        print(f"   Agent ID: {agent_id}")
        print(f"   Agent Name: {agent_name}")
        print(f"   Action Group ID: {action_group_id}")
        print(f"   Alias ID: {alias_id}")
        print(f"   Type: {agent_type}")
        print(f"\n🧪 Test the agent:")
        print(f"   aws bedrock-agent-runtime invoke-agent \\")
        print(f"     --agent-id {agent_id} \\")
        print(f"     --agent-alias-id {alias_id} \\")
        print(f"     --session-id test-session \\")
        print(f"     --input-text 'Show customers from California' \\")
        print(f"     --region {args.region} \\")
        print(f"     /tmp/agent_response.json")


if __name__ == "__main__":
    main()
