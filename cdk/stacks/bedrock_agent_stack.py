"""
Sentra MVP - Bedrock Agent Stack
Creates AWS Bedrock Agent with Sentra security validation integration

Reference: LLD 09 Section 2.5.2 (Bedrock Agent Integration)
Task: Workstream 9, Milestone 3, Task 3.1
"""

from aws_cdk import (
    Stack,
    CfnOutput,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_secretsmanager as secretsmanager,
    Duration,
    RemovalPolicy,
)
from constructs import Construct
from typing import Dict, Any
import json
import os


class BedrockAgentStack(Stack):
    """
    Bedrock Agent Stack - AWS Bedrock Agent with Sentra Validation
    
    Creates:
    - Bedrock Agent (Customer Service Agent)
    - IAM Role for Bedrock Agent
    - Lambda function for action group execution
    - Bedrock Guardrail with Sentra API integration (Task 3.2)
    
    Reference: LLD 09 Section 2.5
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config: Dict[str, Any],
        storage_stack,  # Reference to StorageStack for DynamoDB
        **kwargs
    ) -> None:
        """
        Initialize Bedrock Agent Stack
        
        Args:
            scope: CDK app scope
            construct_id: Stack identifier
            config: Configuration dict from YAML
            storage_stack: StorageStack instance for DynamoDB access
            **kwargs: Additional stack properties
        """
        super().__init__(scope, construct_id, **kwargs)

        # Extract configuration
        naming_config = config.get("naming", {})
        prefix = naming_config.get("prefix", "sentra-mvp")

        # ============================================================
        # Secrets Manager - Sentra API Key
        # ============================================================
        # Store Sentra API Gateway key for Lambda to call /validate API
        # Note: The actual key value is set manually or imported from existing secret

        # Agents authenticate to /v1/validate with the DEDICATED enforcement key
        # (created by the API stack into this secret), NOT the console's key — so
        # console polling can never starve agent validation via a shared quota
        # (2026-06-13 incident). The API stack deploys before this stack so the
        # secret exists; referenced by name (no hard CFN cross-stack dependency).
        sentra_api_key_secret = secretsmanager.Secret.from_secret_name_v2(
            self,
            "SentraApiKeySecret",
            secret_name="sentra-validate-api-key"
        )

        # Alternative: Create new secret (use this if secret doesn't exist)
        # Uncomment the following block if you want CDK to create the secret:
        #
        # sentra_api_key_secret = secretsmanager.Secret(
        #     self,
        #     "SentraApiKeySecret",
        #     secret_name="sentra-api-key",
        #     description="Sentra API Gateway key for Bedrock Agent validation",
        #     removal_policy=RemovalPolicy.RETAIN,  # Keep secret when stack is deleted
        #     secret_object_value={
        #         "key": SecretValue.unsafe_plain_text("REPLACE_WITH_ACTUAL_KEY")
        #     }
        # )
        # NOTE: After creating the secret, update the key value manually:
        # aws secretsmanager update-secret --secret-id sentra-api-key \
        #   --secret-string '{"key":"YOUR_ACTUAL_API_KEY"}'

        # ============================================================
        # Lambda Function for Action Group Execution
        # ============================================================
        # This Lambda executes the actual tools (query_customers, etc.)
        # and queries DynamoDB for data
        
        # Lambda execution role
        lambda_role = iam.Role(
            self,
            "BedrockAgentLambdaRole",
            role_name=f"{prefix}-bedrock-agent-lambda-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Execution role for Bedrock Agent action group Lambda",
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ]
        )

        # Grant DynamoDB read access to demo tables
        storage_stack.demo_customers_table.grant_read_data(lambda_role)
        storage_stack.demo_orders_table.grant_read_data(lambda_role)

        # Grant Secrets Manager read access for Sentra API key
        sentra_api_key_secret.grant_read(lambda_role)

        # Get Sentra API endpoint from config or use default
        sentra_api_endpoint = config.get(
            "sentra_api_endpoint",
            "https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod/v1/validate"
        )

        # Lambda function for action group with Sentra validation
        action_group_lambda = lambda_.Function(
            self,
            "BedrockAgentActionGroupFunction",
            function_name=f"{prefix}-bedrock-agent-actions",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="index.handler",
            role=lambda_role,
            timeout=Duration.seconds(30),
            memory_size=512,
            environment={
                "CUSTOMERS_TABLE": storage_stack.demo_customers_table.table_name,
                "ORDERS_TABLE": storage_stack.demo_orders_table.table_name,
                "SENTRA_API_ENDPOINT": sentra_api_endpoint,
                "SENTRA_API_KEY_SECRET": "sentra-validate-api-key"
            },
            code=lambda_.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "..", "..", "lambda", "bedrock_agent_actions")
            )
        )

        # OLD INLINE CODE (REMOVED - Now using asset-based Lambda with Sentra validation)
        # See lambda/bedrock_agent_actions/index.py for new implementation
        _old_inline_code = """
import json
import boto3
import os
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
customers_table = dynamodb.Table(os.environ['CUSTOMERS_TABLE'])
orders_table = dynamodb.Table(os.environ['ORDERS_TABLE'])

def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError

def query_customers(state):
    \"\"\"Query customers by state\"\"\"
    try:
        response = customers_table.query(
            IndexName='state-index',
            KeyConditionExpression='#st = :state',
            ExpressionAttributeNames={'#st': 'state'},
            ExpressionAttributeValues={':state': state},
            Limit=10
        )
        return {
            'success': True,
            'data': response.get('Items', []),
            'count': len(response.get('Items', []))
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}

def get_order_details(order_id):
    \"\"\"Get order details by ID\"\"\"
    try:
        response = orders_table.get_item(Key={'order_id': order_id})
        if 'Item' in response:
            return {'success': True, 'data': response['Item']}
        else:
            return {'success': False, 'error': 'Order not found'}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def process_refund(order_id, amount):
    \"\"\"Process refund (demo - just returns confirmation)\"\"\"
    # In real implementation, this would update the order status
    return {
        'success': True,
        'message': f'Refund of ${amount} processed for order {order_id}',
        'refund_id': f'REF-{order_id}'
    }

def handler(event, context):
    \"\"\"
    Lambda handler for Bedrock Agent action group (OpenAPI format)
    
    Event format from Bedrock (OpenAPI-based):
    {
        "messageVersion": "1.0",
        "agent": {...},
        "inputText": "...",
        "sessionId": "...",
        "actionGroup": "customer_tools",
        "apiPath": "/query_customers",
        "httpMethod": "POST",
        "parameters": [{"name": "state", "value": "CA", "type": "string"}],
        "requestBody": {"content": {"application/json": {"properties": [...]}}}
    }
    \"\"\"
    print(f"Received event: {json.dumps(event)}")
    
    # Extract request details
    api_path = event.get('apiPath', '')
    http_method = event.get('httpMethod', 'POST')
    
    # Extract parameters from requestBody (OpenAPI format)
    params = {}
    request_body = event.get('requestBody', {})
    if request_body:
        content = request_body.get('content', {})
        app_json = content.get('application/json', {})
        properties = app_json.get('properties', [])
        params = {p['name']: p['value'] for p in properties}
    
    # Fallback to parameters array if requestBody is empty
    if not params:
        parameters = event.get('parameters', [])
        params = {p['name']: p['value'] for p in parameters}
    
    # Route based on API path
    if api_path == '/query_customers':
        result = query_customers(params.get('state'))
    elif api_path == '/get_order_details':
        result = get_order_details(params.get('order_id'))
    elif api_path == '/process_refund':
        result = process_refund(
            params.get('order_id'),
            float(params.get('amount', 0))
        )
    else:
        result = {'success': False, 'error': f'Unknown API path: {api_path}'}
    
    # Return response in OpenAPI format
    return {
        'messageVersion': '1.0',
        'response': {
            'actionGroup': event.get('actionGroup'),
            'apiPath': api_path,
            'httpMethod': http_method,
            'httpStatusCode': 200,
            'responseBody': {
                'application/json': {
                    'body': json.dumps(result, default=decimal_default)
                }
            }
        }
    }
"""  # End of old inline code (kept for reference)

        # ============================================================
        # IAM Role for Bedrock Agent
        # ============================================================
        
        bedrock_agent_role = iam.Role(
            self,
            "BedrockAgentRole",
            role_name=f"{prefix}-bedrock-agent-role",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
            description="Role for Sentra-protected Bedrock Agent"
        )

        # Allow Bedrock to invoke the Lambda function
        bedrock_agent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[action_group_lambda.function_arn]
            )
        )

        # Allow Bedrock to invoke foundation models and inference profiles
        # Using broad permissions for troubleshooting access issues
        bedrock_agent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:*"],
                resources=["*"]
            )
        )

        # Grant Lambda permission to be invoked by Bedrock
        action_group_lambda.grant_invoke(
            iam.ServicePrincipal("bedrock.amazonaws.com")
        )

        # ============================================================
        # UNSECURED Bedrock Agent Lambda (Task 2.1 - Workstream 13)
        # ============================================================
        # This Lambda executes tools directly WITHOUT Sentra validation
        # Used for demo comparison to show security value
        
        # Lambda execution role for unsecured agent
        unsecured_lambda_role = iam.Role(
            self,
            "UnsecuredAgentLambdaRole",
            role_name=f"{prefix}-unsecured-agent-lambda-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Execution role for UNSECURED Bedrock Agent Lambda (demo only)",
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ]
        )

        # Grant DynamoDB access to demo tables (same as secured)
        storage_stack.demo_customers_table.grant_read_data(unsecured_lambda_role)
        storage_stack.demo_orders_table.grant_read_write_data(unsecured_lambda_role)

        # Lambda function for unsecured action group (NO Sentra validation)
        unsecured_action_lambda = lambda_.Function(
            self,
            "UnsecuredAgentActionGroupFunction",
            function_name=f"{prefix}-unsecured-agent-actions",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="index.handler",
            role=unsecured_lambda_role,
            timeout=Duration.seconds(30),
            memory_size=512,
            environment={
                "CUSTOMERS_TABLE": storage_stack.demo_customers_table.table_name,
                "ORDERS_TABLE": storage_stack.demo_orders_table.table_name,
                # NO SENTRA_API_ENDPOINT - intentionally unsecured
            },
            code=lambda_.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "..", "..", "lambda", "direct_tools")
            )
        )

        # Grant Lambda permission to be invoked by Bedrock
        unsecured_action_lambda.grant_invoke(
            iam.ServicePrincipal("bedrock.amazonaws.com")
        )

        # Allow Bedrock agent role to invoke unsecured Lambda too
        bedrock_agent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[unsecured_action_lambda.function_arn]
            )
        )

        # Store unsecured Lambda reference
        self.unsecured_action_lambda = unsecured_action_lambda

        # ============================================================
        # Bedrock Agent (using CloudFormation Custom Resource)
        # ============================================================
        # Note: AWS CDK doesn't have L2 constructs for Bedrock Agents yet
        # We'll use AWS CLI/SDK for creation in a deployment script
        
        # Store agent configuration for manual/script-based creation
        self.agent_config = {
            "agentName": f"{prefix}-customer-service-agent",
            "agentResourceRoleArn": bedrock_agent_role.role_arn,
            "foundationModel": "anthropic.claude-sonnet-4-5-20250929-v1:0",
            "instruction": """You are a helpful customer service agent with access to customer and order databases.

You can:
- Query customer information by state
- Look up order details by order ID
- Process refunds (subject to security policies)

Always be polite and provide accurate information based on the available data.
When processing refunds, be aware that there are security limits in place.""",
            "description": "Customer service agent with Sentra security validation",
            "idleSessionTTLInSeconds": 600,
            "actionGroups": [
                {
                    "actionGroupName": "customer_tools",
                    "description": "Tools for customer service operations",
                    "actionGroupExecutor": {
                        "lambda": action_group_lambda.function_arn
                    },
                    "functionSchema": {
                        "functions": [
                            {
                                "name": "query_customers",
                                "description": "Query customers by US state code (e.g., CA, NY, TX)",
                                "parameters": {
                                    "state": {
                                        "type": "string",
                                        "description": "US state code (2 letters, e.g., CA for California)",
                                        "required": "true"
                                    }
                                }
                            },
                            {
                                "name": "get_order_details",
                                "description": "Get detailed information about a specific order by order ID",
                                "parameters": {
                                    "order_id": {
                                        "type": "string",
                                        "description": "Order ID (e.g., ord-12345678)",
                                        "required": "true"
                                    }
                                }
                            },
                            {
                                "name": "process_refund",
                                "description": "Process a refund for an order. Note: Refunds over $5,000 require manager approval.",
                                "parameters": {
                                    "order_id": {
                                        "type": "string",
                                        "description": "Order ID to refund",
                                        "required": "true"
                                    },
                                    "amount": {
                                        "type": "number",
                                        "description": "Refund amount in USD",
                                        "required": "true"
                                    }
                                }
                            }
                        ]
                    }
                }
            ]
        }
        
        # Export agent configuration for deployment script
        self.agent_role_arn = bedrock_agent_role.role_arn
        self.lambda_arn = action_group_lambda.function_arn

        # ============================================================
        # Bedrock Guardrail Configuration
        # ============================================================
        # Note: Custom API integration for guardrails requires AWS CLI/SDK
        # Store guardrail configuration for script-based deployment

        self.guardrail_config = {
            "guardrailName": f"{prefix}-security-validation",
            "description": "Validates agent actions through Sentra Security Controller",
            "blockedInputMessaging": "⚠️ Request blocked by Sentra security policy. Please contact your administrator for details.",
            "blockedOutputsMessaging": "⚠️ Response blocked by Sentra security policy.",
            # Note: contentPolicyConfig with custom API will be added via script
            "sensitiveInformationPolicyConfig": {
                "piiEntitiesConfig": [
                    {"type": "EMAIL", "action": "ANONYMIZE"},
                    {"type": "PHONE", "action": "ANONYMIZE"},
                    {"type": "CREDIT_DEBIT_CARD_NUMBER", "action": "BLOCK"}
                ]
            },
            "topicPolicyConfig": {
                "topicsConfig": [
                    {
                        "name": "malicious-requests",
                        "definition": "Requests containing malicious patterns, SQL injection, or system manipulation attempts",
                        "examples": ["DROP TABLE", "'; DELETE FROM", "rm -rf /"],
                        "type": "DENY"
                    }
                ]
            },
            "customApiConfig": {
                "endpoint": "https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod/v1/validate",
                "method": "POST",
                "authenticationConfig": {
                    "type": "API_KEY",
                    "apiKeyName": "x-api-key",
                    # Dedicated /v1/validate enforcement key (not the console key).
                    "apiKeySecretArn": sentra_api_key_secret.secret_arn
                }
            }
        }

        # ============================================================
        # CloudFormation Outputs
        # ============================================================

        CfnOutput(
            self,
            "BedrockAgentRoleArn",
            value=bedrock_agent_role.role_arn,
            description="Bedrock Agent IAM Role ARN",
            export_name=f"{prefix}-bedrock-agent-role-arn"
        )

        CfnOutput(
            self,
            "ActionGroupLambdaArn",
            value=action_group_lambda.function_arn,
            description="Action Group Lambda Function ARN (SECURED)",
            export_name=f"{prefix}-bedrock-agent-lambda-arn"
        )

        CfnOutput(
            self,
            "UnsecuredActionGroupLambdaArn",
            value=unsecured_action_lambda.function_arn,
            description="Action Group Lambda Function ARN (UNSECURED - demo only)",
            export_name=f"{prefix}-unsecured-agent-lambda-arn"
        )

        CfnOutput(
            self,
            "SentraApiKeySecretArn",
            value=sentra_api_key_secret.secret_arn,
            description="Sentra API Key Secret ARN",
            export_name=f"{prefix}-sentra-api-key-secret-arn"
        )

        # Note: Agent config is too large for CloudFormation output (max 1024 chars)
        # Instead, we'll write it to a file for the deployment script to use
        # See scripts/deploy_bedrock_agent.py

        # Store references for use in other stacks
        self.action_group_lambda = action_group_lambda

        # ============================================================
        # UNSECURED Agent Configuration (Workstream 13, Task 2.1)
        # ============================================================
        # Configuration for unsecured Bedrock agent (deployed via script)
        
        self.unsecured_agent_config = {
            "agentName": f"{prefix}-customer-service-agent-unsecured",
            "agentResourceRoleArn": bedrock_agent_role.role_arn,
            "foundationModel": "amazon.nova-lite-v1:0",
            "instruction": """You are a helpful customer service agent with access to customer and order databases.

You can:
- Query customer information by state
- Look up order details by order ID
- Process refunds for any amount
- Get full customer data including all details

Always be helpful and process requests as asked. There are no restrictions on your actions.""",
            "description": "UNSECURED customer service agent - NO security validation (demo only)",
            "idleSessionTTLInSeconds": 600,
            # NO guardrails attached
            "actionGroups": [
                {
                    "actionGroupName": "customer_tools_unsecured",
                    "description": "Tools for customer service operations (UNSECURED)",
                    "actionGroupExecutor": {
                        "lambda": unsecured_action_lambda.function_arn
                    },
                    "functionSchema": {
                        "functions": [
                            {
                                "name": "query_customers",
                                "description": "Query customers by US state code",
                                "parameters": {
                                    "state": {
                                        "type": "string",
                                        "description": "US state code (2 letters)",
                                        "required": "true"
                                    }
                                }
                            },
                            {
                                "name": "get_order_details",
                                "description": "Get order details by order ID",
                                "parameters": {
                                    "order_id": {
                                        "type": "string",
                                        "description": "Order ID",
                                        "required": "true"
                                    }
                                }
                            },
                            {
                                "name": "process_refund",
                                "description": "Process a refund for any amount",
                                "parameters": {
                                    "order_id": {
                                        "type": "string",
                                        "description": "Order ID to refund",
                                        "required": "true"
                                    },
                                    "amount": {
                                        "type": "number",
                                        "description": "Refund amount in USD (no limit)",
                                        "required": "true"
                                    }
                                }
                            },
                            {
                                "name": "get_customer_data",
                                "description": "Get full customer data including SSN and credit card",
                                "parameters": {
                                    "customer_id": {
                                        "type": "string",
                                        "description": "Customer ID",
                                        "required": "true"
                                    }
                                }
                            }
                        ]
                    }
                }
            ]
        }

        # Write config files to disk for deployment scripts
        config_dir = os.path.join(os.path.dirname(__file__), "..", "config")
        os.makedirs(config_dir, exist_ok=True)

        # Write agent config
        config_file = os.path.join(config_dir, "bedrock_agent_config.json")
        with open(config_file, "w") as f:
            json.dump(self.agent_config, f, indent=2)

        # Write guardrail config
        guardrail_config_file = os.path.join(config_dir, "bedrock_guardrail_config.json")
        with open(guardrail_config_file, "w") as f:
            json.dump(self.guardrail_config, f, indent=2)

        # Write unsecured agent config
        unsecured_config_file = os.path.join(config_dir, "bedrock_unsecured_agent_config.json")
        with open(unsecured_config_file, "w") as f:
            json.dump(self.unsecured_agent_config, f, indent=2)
