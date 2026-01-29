#!/usr/bin/env python3
"""
Test script to validate Pydantic schemas against DynamoDB data.
"""
import boto3
import sys
from schemas import (
    Agent,
    Tool,
    PolicyMetadata,
    SigmaRuleMetadata,
)


def test_agent_schema():
    """Test Agent schema validation."""
    print("\n" + "=" * 60)
    print("Testing Agent Schema")
    print("=" * 60)
    
    try:
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        table = dynamodb.Table('sentra-agent-registry')
        
        response = table.scan(Limit=5)
        items = response.get('Items', [])
        
        if not items:
            print("⚠️  No agents found in table")
            return False
        
        print(f"Found {len(items)} agents")
        
        valid_count = 0
        for item in items:
            try:
                agent = Agent(**item)
                print(f"✅ Valid: {agent.agent_id} - {agent.name}")
                valid_count += 1
            except Exception as e:
                print(f"❌ Invalid: {item.get('agent_id', 'unknown')}")
                print(f"   Error: {str(e)}")
                return False
        
        print(f"\n✅ All {valid_count} agents validated successfully")
        return True
        
    except Exception as e:
        print(f"❌ Error accessing table: {str(e)}")
        return False


def test_tool_schema():
    """Test Tool schema validation."""
    print("\n" + "=" * 60)
    print("Testing Tool Schema")
    print("=" * 60)
    
    try:
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        table = dynamodb.Table('sentra-tool-registry')
        
        response = table.scan(Limit=10)
        items = response.get('Items', [])
        
        if not items:
            print("⚠️  No tools found in table")
            return False
        
        print(f"Found {len(items)} tools")
        
        valid_count = 0
        for item in items:
            try:
                tool = Tool(**item)
                print(f"✅ Valid: {tool.tool_id} ({tool.tool_type}) - {tool.name}")
                valid_count += 1
            except Exception as e:
                print(f"❌ Invalid: {item.get('tool_id', 'unknown')}")
                print(f"   Error: {str(e)}")
                return False
        
        print(f"\n✅ All {valid_count} tools validated successfully")
        return True
        
    except Exception as e:
        print(f"❌ Error accessing table: {str(e)}")
        return False


def test_policy_metadata_schema():
    """Test PolicyMetadata schema validation."""
    print("\n" + "=" * 60)
    print("Testing Policy Metadata Schema")
    print("=" * 60)
    
    try:
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        table = dynamodb.Table('sentra-policies-metadata')
        
        response = table.scan(Limit=10)
        items = response.get('Items', [])
        
        if not items:
            print("⚠️  No policy metadata found in table")
            return False
        
        print(f"Found {len(items)} policy metadata items")
        
        valid_count = 0
        for item in items:
            try:
                policy = PolicyMetadata(**item)
                print(f"✅ Valid: {policy.policy_id} - {policy.name} (v{policy.version})")
                valid_count += 1
            except Exception as e:
                print(f"❌ Invalid: {item.get('policy_id', 'unknown')}")
                print(f"   Error: {str(e)}")
                return False
        
        print(f"\n✅ All {valid_count} policy metadata items validated successfully")
        return True
        
    except Exception as e:
        print(f"❌ Error accessing table: {str(e)}")
        return False


def test_sigma_rule_metadata_schema():
    """Test SigmaRuleMetadata schema validation."""
    print("\n" + "=" * 60)
    print("Testing Sigma Rule Metadata Schema")
    print("=" * 60)
    
    try:
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        table = dynamodb.Table('sentra-sigma-rules-metadata')
        
        response = table.scan(Limit=10)
        items = response.get('Items', [])
        
        if not items:
            print("⚠️  No Sigma rule metadata found in table")
            return False
        
        print(f"Found {len(items)} Sigma rule metadata items")
        
        valid_count = 0
        for item in items:
            try:
                rule = SigmaRuleMetadata(**item)
                print(f"✅ Valid: {rule.rule_id} ({rule.level}) - {rule.title}")
                valid_count += 1
            except Exception as e:
                print(f"❌ Invalid: {item.get('rule_id', 'unknown')}")
                print(f"   Error: {str(e)}")
                return False
        
        print(f"\n✅ All {valid_count} Sigma rule metadata items validated successfully")
        return True
        
    except Exception as e:
        print(f"❌ Error accessing table: {str(e)}")
        return False


def main():
    """Run all schema validation tests."""
    print("=" * 60)
    print("Sentra Data Model - Schema Validation Tests")
    print("=" * 60)
    
    results = {
        "Agent Schema": test_agent_schema(),
        "Tool Schema": test_tool_schema(),
        "Policy Metadata Schema": test_policy_metadata_schema(),
        "Sigma Rule Metadata Schema": test_sigma_rule_metadata_schema(),
    }
    
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    all_passed = all(results.values())
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ All schema validation tests passed!")
        print("=" * 60)
        return 0
    else:
        print("❌ Some schema validation tests failed")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
