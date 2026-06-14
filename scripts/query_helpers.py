#!/usr/bin/env python3
"""
Query helper functions for Sentra data model.
Provides reusable functions to query DynamoDB tables and S3 content.
"""
import boto3
import yaml
from typing import List, Optional, Dict, Any
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from schemas import (
    Agent,
    Tool,
    PolicyMetadata,
    AgentPolicyDocument,
    SigmaRuleMetadata,
    SigmaRuleDocument,
)

import _tenancy  # shared tenancy helpers (workstream T08)


# Custom exceptions
class AgentNotFoundError(Exception):
    """Raised when agent is not found."""
    pass


class ToolNotFoundError(Exception):
    """Raised when tool is not found."""
    pass


class PolicyNotFoundError(Exception):
    """Raised when policy is not found."""
    pass


class SigmaRuleNotFoundError(Exception):
    """Raised when Sigma rule is not found."""
    pass


class S3ContentError(Exception):
    """Raised when S3 content cannot be retrieved."""
    pass


# Initialize AWS clients
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
s3_client = boto3.client('s3', region_name='us-east-1')


# Agent queries
def get_agent_by_id(agent_id: str) -> Agent:
    """
    Get agent by ID from sentra-agent-registry.
    
    Args:
        agent_id: Unique agent identifier
        
    Returns:
        Agent object validated with Pydantic
        
    Raises:
        AgentNotFoundError: If agent not found
    """
    try:
        table = dynamodb.Table(_tenancy.table_name('sentra-agent-registry', 'sentra-agent-registry-v2'))
        response = table.get_item(Key=_tenancy.item_key('agent_id', agent_id))

        if 'Item' not in response:
            raise AgentNotFoundError(f"Agent not found: {agent_id}")
        
        return Agent(**response['Item'])
        
    except ClientError as e:
        raise AgentNotFoundError(f"Error retrieving agent {agent_id}: {str(e)}")


def list_agents(status: Optional[str] = None) -> List[Agent]:
    """
    List all agents, optionally filtered by status.
    
    Args:
        status: Optional status filter (active, inactive, deploying, failed)
        
    Returns:
        List of Agent objects
    """
    try:
        table = dynamodb.Table(_tenancy.table_name('sentra-agent-registry', 'sentra-agent-registry-v2'))

        if status:
            # Query using status-index GSI
            response = table.query(
                IndexName='status-index',
                KeyConditionExpression=_tenancy.status_index_condition(status)
            )
        else:
            # List all agents (tenant-scoped Query when v2, else full scan)
            response = _tenancy.query_or_scan(table)
        
        items = response.get('Items', [])
        return [Agent(**item) for item in items]
        
    except ClientError as e:
        raise AgentNotFoundError(f"Error listing agents: {str(e)}")


# Tool queries
def get_tool_by_id(tool_id: str) -> Tool:
    """
    Get tool by ID from sentra-tool-registry.
    
    Args:
        tool_id: Unique tool identifier
        
    Returns:
        Tool object validated with Pydantic
        
    Raises:
        ToolNotFoundError: If tool not found
    """
    try:
        table = dynamodb.Table('sentra-tool-registry')
        response = table.get_item(Key={'tool_id': tool_id})
        
        if 'Item' not in response:
            raise ToolNotFoundError(f"Tool not found: {tool_id}")
        
        return Tool(**response['Item'])
        
    except ClientError as e:
        raise ToolNotFoundError(f"Error retrieving tool {tool_id}: {str(e)}")


def list_tools_by_type(tool_type: str) -> List[Tool]:
    """
    List tools by type (READ or WRITE).
    
    Args:
        tool_type: Tool type filter (READ or WRITE)
        
    Returns:
        List of Tool objects
    """
    try:
        table = dynamodb.Table('sentra-tool-registry')
        
        # Query using type-index GSI
        response = table.query(
            IndexName='type-index',
            KeyConditionExpression=Key('tool_type').eq(tool_type)
        )
        
        items = response.get('Items', [])
        return [Tool(**item) for item in items]
        
    except ClientError as e:
        raise ToolNotFoundError(f"Error listing tools by type {tool_type}: {str(e)}")


def list_all_tools() -> List[Tool]:
    """
    List all tools.
    
    Returns:
        List of Tool objects
    """
    try:
        table = dynamodb.Table('sentra-tool-registry')
        response = table.scan()
        
        items = response.get('Items', [])
        return [Tool(**item) for item in items]
        
    except ClientError as e:
        raise ToolNotFoundError(f"Error listing tools: {str(e)}")


# Policy queries
def get_policy_metadata(policy_id: str) -> PolicyMetadata:
    """
    Get policy metadata from sentra-policies-metadata.
    
    Args:
        policy_id: Unique policy identifier
        
    Returns:
        PolicyMetadata object
        
    Raises:
        PolicyNotFoundError: If policy not found
    """
    try:
        table = dynamodb.Table(_tenancy.table_name('sentra-policies-metadata', 'sentra-policies-metadata-v2'))
        response = table.get_item(Key=_tenancy.item_key('policy_id', policy_id))

        if 'Item' not in response:
            raise PolicyNotFoundError(f"Policy metadata not found: {policy_id}")
        
        return PolicyMetadata(**response['Item'])
        
    except ClientError as e:
        raise PolicyNotFoundError(f"Error retrieving policy metadata {policy_id}: {str(e)}")


def get_policy_full(policy_id: str) -> AgentPolicyDocument:
    """
    Get full policy document (metadata from DynamoDB + content from S3).
    
    Args:
        policy_id: Unique policy identifier
        
    Returns:
        AgentPolicyDocument object with full policy content
        
    Raises:
        PolicyNotFoundError: If policy not found
        S3ContentError: If S3 content cannot be retrieved
    """
    try:
        # Step 1: Get metadata from DynamoDB
        metadata = get_policy_metadata(policy_id)
        
        # Step 2: Download YAML from S3
        try:
            response = s3_client.get_object(
                Bucket=metadata.s3_bucket,
                Key=metadata.s3_key
            )
            content = response['Body'].read().decode('utf-8')
            
        except ClientError as e:
            raise S3ContentError(f"Error downloading policy from S3: {str(e)}")
        
        # Step 3: Parse YAML and validate with Pydantic
        try:
            policy_data = yaml.safe_load(content)
            return AgentPolicyDocument(**policy_data)
            
        except Exception as e:
            raise S3ContentError(f"Error parsing policy YAML: {str(e)}")
        
    except PolicyNotFoundError:
        raise
    except S3ContentError:
        raise
    except Exception as e:
        raise PolicyNotFoundError(f"Error retrieving full policy {policy_id}: {str(e)}")


def list_policies_by_agent(agent_id: str) -> List[PolicyMetadata]:
    """
    List policy metadata by agent ID.
    
    Args:
        agent_id: Agent identifier
        
    Returns:
        List of PolicyMetadata objects
    """
    try:
        table = dynamodb.Table(_tenancy.table_name('sentra-policies-metadata', 'sentra-policies-metadata-v2'))

        # Query using agent-index GSI (composite tenant_agent_id PK when v2)
        response = table.query(
            IndexName='agent-index',
            KeyConditionExpression=_tenancy.agent_index_condition(agent_id)
        )
        
        items = response.get('Items', [])
        return [PolicyMetadata(**item) for item in items]
        
    except ClientError as e:
        raise PolicyNotFoundError(f"Error listing policies for agent {agent_id}: {str(e)}")


def list_policies_by_status(status: str) -> List[PolicyMetadata]:
    """
    List policy metadata by status.
    
    Args:
        status: Policy status (active or disabled)
        
    Returns:
        List of PolicyMetadata objects
    """
    try:
        table = dynamodb.Table(_tenancy.table_name('sentra-policies-metadata', 'sentra-policies-metadata-v2'))

        # Query using status-index GSI (tenant_id PK + status SK when v2)
        response = table.query(
            IndexName='status-index',
            KeyConditionExpression=_tenancy.status_index_condition(status)
        )
        
        items = response.get('Items', [])
        return [PolicyMetadata(**item) for item in items]
        
    except ClientError as e:
        raise PolicyNotFoundError(f"Error listing policies by status {status}: {str(e)}")


# Sigma rule queries
def get_sigma_rule_metadata(rule_id: str) -> SigmaRuleMetadata:
    """
    Get Sigma rule metadata from sentra-sigma-rules-metadata.
    
    Args:
        rule_id: Unique rule identifier
        
    Returns:
        SigmaRuleMetadata object
        
    Raises:
        SigmaRuleNotFoundError: If rule not found
    """
    try:
        table = dynamodb.Table('sentra-sigma-rules-metadata')
        response = table.get_item(Key={'rule_id': rule_id})
        
        if 'Item' not in response:
            raise SigmaRuleNotFoundError(f"Sigma rule metadata not found: {rule_id}")
        
        return SigmaRuleMetadata(**response['Item'])
        
    except ClientError as e:
        raise SigmaRuleNotFoundError(f"Error retrieving Sigma rule metadata {rule_id}: {str(e)}")


def get_sigma_rule_full(rule_id: str) -> SigmaRuleDocument:
    """
    Get full Sigma rule (metadata from DynamoDB + content from S3).
    
    Args:
        rule_id: Unique rule identifier
        
    Returns:
        SigmaRuleDocument object with full rule content
        
    Raises:
        SigmaRuleNotFoundError: If rule not found
        S3ContentError: If S3 content cannot be retrieved
    """
    try:
        # Step 1: Get metadata from DynamoDB
        metadata = get_sigma_rule_metadata(rule_id)
        
        # Step 2: Download YAML from S3
        try:
            response = s3_client.get_object(
                Bucket=metadata.s3_bucket,
                Key=metadata.s3_key
            )
            content = response['Body'].read().decode('utf-8')
            
        except ClientError as e:
            raise S3ContentError(f"Error downloading Sigma rule from S3: {str(e)}")
        
        # Step 3: Parse YAML and validate with Pydantic
        try:
            rule_data = yaml.safe_load(content)
            
            # Convert date objects to strings if present
            if 'date' in rule_data and hasattr(rule_data['date'], 'isoformat'):
                rule_data['date'] = rule_data['date'].isoformat()
            if 'modified' in rule_data and hasattr(rule_data['modified'], 'isoformat'):
                rule_data['modified'] = rule_data['modified'].isoformat()
            
            return SigmaRuleDocument(**rule_data)
            
        except Exception as e:
            raise S3ContentError(f"Error parsing Sigma rule YAML: {str(e)}")
        
    except SigmaRuleNotFoundError:
        raise
    except S3ContentError:
        raise
    except Exception as e:
        raise SigmaRuleNotFoundError(f"Error retrieving full Sigma rule {rule_id}: {str(e)}")


def list_sigma_rules_by_level(level: str) -> List[SigmaRuleMetadata]:
    """
    List Sigma rule metadata by severity level.
    
    Args:
        level: Severity level (critical, high, medium, low)
        
    Returns:
        List of SigmaRuleMetadata objects
    """
    try:
        table = dynamodb.Table('sentra-sigma-rules-metadata')
        
        # Query using level-index GSI
        response = table.query(
            IndexName='level-index',
            KeyConditionExpression=Key('level').eq(level)
        )
        
        items = response.get('Items', [])
        return [SigmaRuleMetadata(**item) for item in items]
        
    except ClientError as e:
        raise SigmaRuleNotFoundError(f"Error listing Sigma rules by level {level}: {str(e)}")


def list_sigma_rules_by_status(status: str) -> List[SigmaRuleMetadata]:
    """
    List Sigma rule metadata by status.
    
    Args:
        status: Rule status (stable, experimental, deprecated, disabled)
        
    Returns:
        List of SigmaRuleMetadata objects
    """
    try:
        table = dynamodb.Table('sentra-sigma-rules-metadata')
        
        # Query using status-index GSI
        response = table.query(
            IndexName='status-index',
            KeyConditionExpression=Key('status').eq(status)
        )
        
        items = response.get('Items', [])
        return [SigmaRuleMetadata(**item) for item in items]
        
    except ClientError as e:
        raise SigmaRuleNotFoundError(f"Error listing Sigma rules by status {status}: {str(e)}")


def list_all_sigma_rules() -> List[SigmaRuleMetadata]:
    """
    List all Sigma rule metadata.
    
    Returns:
        List of SigmaRuleMetadata objects
    """
    try:
        table = dynamodb.Table('sentra-sigma-rules-metadata')
        response = table.scan()
        
        items = response.get('Items', [])
        return [SigmaRuleMetadata(**item) for item in items]
        
    except ClientError as e:
        raise SigmaRuleNotFoundError(f"Error listing Sigma rules: {str(e)}")


# Utility functions
def get_tools_for_agent(agent_id: str) -> List[Tool]:
    """
    Get all allowed tools for an agent.
    
    This function:
    1. Gets policy metadata for the agent
    2. Extracts allowed tool IDs
    3. Fetches full tool definitions from tool registry
    
    Args:
        agent_id: Agent identifier
        
    Returns:
        List of Tool objects
        
    Raises:
        PolicyNotFoundError: If agent policy not found
        ToolNotFoundError: If tool definitions not found
    """
    try:
        # Get policies for agent
        policies = list_policies_by_agent(agent_id)
        
        if not policies:
            raise PolicyNotFoundError(f"No policies found for agent: {agent_id}")
        
        # Get the active policy (assuming one policy per agent for MVP)
        active_policy = next((p for p in policies if p.status == "active"), None)
        
        if not active_policy:
            raise PolicyNotFoundError(f"No active policy found for agent: {agent_id}")
        
        # Get full policy document to access allowed_tools
        full_policy = get_policy_full(active_policy.policy_id)
        
        # Fetch tool definitions
        tools = []
        for tool_id in full_policy.allowed_tools:
            try:
                tool = get_tool_by_id(tool_id)
                tools.append(tool)
            except ToolNotFoundError:
                # Log warning but continue
                print(f"Warning: Tool {tool_id} not found in registry")
                continue
        
        return tools
        
    except PolicyNotFoundError:
        raise
    except Exception as e:
        raise PolicyNotFoundError(f"Error getting tools for agent {agent_id}: {str(e)}")
