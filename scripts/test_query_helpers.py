#!/usr/bin/env python3
"""
Test script for query helper functions.
"""
import sys
from query_helpers import (
    get_agent_by_id,
    list_agents,
    get_tool_by_id,
    list_tools_by_type,
    list_all_tools,
    get_policy_metadata,
    get_policy_full,
    list_policies_by_agent,
    list_policies_by_status,
    get_sigma_rule_metadata,
    get_sigma_rule_full,
    list_sigma_rules_by_level,
    list_sigma_rules_by_status,
    list_all_sigma_rules,
    get_tools_for_agent,
    AgentNotFoundError,
    ToolNotFoundError,
    PolicyNotFoundError,
    SigmaRuleNotFoundError,
)


def test_agent_queries():
    """Test agent query functions."""
    print("\n" + "=" * 60)
    print("Testing Agent Queries")
    print("=" * 60)
    
    try:
        # Test get_agent_by_id
        print("\n1. Testing get_agent_by_id('customer-query-agent')...")
        agent = get_agent_by_id('customer-query-agent')
        print(f"   ✅ Found: {agent.name} (status: {agent.status})")
        
        # Test list_agents
        print("\n2. Testing list_agents()...")
        agents = list_agents()
        print(f"   ✅ Found {len(agents)} agents:")
        for a in agents:
            print(f"      - {a.agent_id}: {a.name}")
        
        # Test list_agents with status filter
        print("\n3. Testing list_agents(status='active')...")
        active_agents = list_agents(status='active')
        print(f"   ✅ Found {len(active_agents)} active agents")
        
        # Test error handling
        print("\n4. Testing error handling (non-existent agent)...")
        try:
            get_agent_by_id('non-existent-agent')
            print("   ❌ Should have raised AgentNotFoundError")
            return False
        except AgentNotFoundError:
            print("   ✅ Correctly raised AgentNotFoundError")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Error: {str(e)}")
        return False


def test_tool_queries():
    """Test tool query functions."""
    print("\n" + "=" * 60)
    print("Testing Tool Queries")
    print("=" * 60)
    
    try:
        # Test get_tool_by_id
        print("\n1. Testing get_tool_by_id('query_customers')...")
        tool = get_tool_by_id('query_customers')
        print(f"   ✅ Found: {tool.name} (type: {tool.tool_type})")
        
        # Test list_tools_by_type
        print("\n2. Testing list_tools_by_type('READ')...")
        read_tools = list_tools_by_type('READ')
        print(f"   ✅ Found {len(read_tools)} READ tools")
        
        print("\n3. Testing list_tools_by_type('WRITE')...")
        write_tools = list_tools_by_type('WRITE')
        print(f"   ✅ Found {len(write_tools)} WRITE tools")
        
        # Test list_all_tools
        print("\n4. Testing list_all_tools()...")
        all_tools = list_all_tools()
        print(f"   ✅ Found {len(all_tools)} total tools")
        
        # Test error handling
        print("\n5. Testing error handling (non-existent tool)...")
        try:
            get_tool_by_id('non-existent-tool')
            print("   ❌ Should have raised ToolNotFoundError")
            return False
        except ToolNotFoundError:
            print("   ✅ Correctly raised ToolNotFoundError")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Error: {str(e)}")
        return False


def test_policy_queries():
    """Test policy query functions."""
    print("\n" + "=" * 60)
    print("Testing Policy Queries")
    print("=" * 60)
    
    try:
        # Test list_policies_by_status
        print("\n1. Testing list_policies_by_status('active')...")
        active_policies = list_policies_by_status('active')
        print(f"   ✅ Found {len(active_policies)} active policies")
        
        if not active_policies:
            print("   ⚠️  No policies found, skipping remaining tests")
            return True
        
        policy_id = active_policies[0].policy_id
        
        # Test get_policy_metadata
        print(f"\n2. Testing get_policy_metadata('{policy_id}')...")
        metadata = get_policy_metadata(policy_id)
        print(f"   ✅ Found: {metadata.name} (v{metadata.version})")
        print(f"      - S3 Key: {metadata.s3_key}")
        print(f"      - Allowed Tools: {metadata.allowed_tools_count}")
        print(f"      - Policies: {metadata.policies_count}")
        
        # Test get_policy_full
        print(f"\n3. Testing get_policy_full('{policy_id}')...")
        full_policy = get_policy_full(policy_id)
        print(f"   ✅ Found full policy: {full_policy.policy_id}")
        print(f"      - Allowed Tools: {len(full_policy.allowed_tools)}")
        print(f"      - Policy Rules: {len(full_policy.policies)}")
        
        # Test list_policies_by_agent
        print(f"\n4. Testing list_policies_by_agent('{metadata.agent_id}')...")
        agent_policies = list_policies_by_agent(metadata.agent_id)
        print(f"   ✅ Found {len(agent_policies)} policies for agent")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_sigma_rule_queries():
    """Test Sigma rule query functions."""
    print("\n" + "=" * 60)
    print("Testing Sigma Rule Queries")
    print("=" * 60)
    
    try:
        # Test list_all_sigma_rules
        print("\n1. Testing list_all_sigma_rules()...")
        all_rules = list_all_sigma_rules()
        print(f"   ✅ Found {len(all_rules)} Sigma rules")
        
        if not all_rules:
            print("   ⚠️  No rules found, skipping remaining tests")
            return True
        
        rule_id = all_rules[0].rule_id
        
        # Test get_sigma_rule_metadata
        print(f"\n2. Testing get_sigma_rule_metadata('{rule_id}')...")
        metadata = get_sigma_rule_metadata(rule_id)
        print(f"   ✅ Found: {metadata.title}")
        print(f"      - Level: {metadata.level}")
        print(f"      - Status: {metadata.status}")
        print(f"      - Patterns: {metadata.patterns_count}")
        
        # Test get_sigma_rule_full
        print(f"\n3. Testing get_sigma_rule_full('{rule_id}')...")
        full_rule = get_sigma_rule_full(rule_id)
        print(f"   ✅ Found full rule: {full_rule.title}")
        if full_rule.detection.patterns:
            print(f"      - Detection Patterns: {len(full_rule.detection.patterns)}")
        print(f"      - Condition: {full_rule.detection.condition}")
        
        # Test list_sigma_rules_by_level
        print("\n4. Testing list_sigma_rules_by_level('high')...")
        high_rules = list_sigma_rules_by_level('high')
        print(f"   ✅ Found {len(high_rules)} high-level rules")
        
        print("\n5. Testing list_sigma_rules_by_level('critical')...")
        critical_rules = list_sigma_rules_by_level('critical')
        print(f"   ✅ Found {len(critical_rules)} critical-level rules")
        
        # Test list_sigma_rules_by_status
        print("\n6. Testing list_sigma_rules_by_status('stable')...")
        stable_rules = list_sigma_rules_by_status('stable')
        print(f"   ✅ Found {len(stable_rules)} stable rules")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_utility_functions():
    """Test utility functions."""
    print("\n" + "=" * 60)
    print("Testing Utility Functions")
    print("=" * 60)
    
    try:
        # Test get_tools_for_agent
        print("\n1. Testing get_tools_for_agent('customer-query-agent')...")
        tools = get_tools_for_agent('customer-query-agent')
        print(f"   ✅ Found {len(tools)} allowed tools:")
        for tool in tools:
            print(f"      - {tool.tool_id}: {tool.name} ({tool.tool_type})")
        
        print("\n2. Testing get_tools_for_agent('payment-agent')...")
        tools = get_tools_for_agent('payment-agent')
        print(f"   ✅ Found {len(tools)} allowed tools:")
        for tool in tools:
            print(f"      - {tool.tool_id}: {tool.name} ({tool.tool_type})")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all query helper tests."""
    print("=" * 60)
    print("Sentra Data Model - Query Helper Tests")
    print("=" * 60)
    
    results = {
        "Agent Queries": test_agent_queries(),
        "Tool Queries": test_tool_queries(),
        "Policy Queries": test_policy_queries(),
        "Sigma Rule Queries": test_sigma_rule_queries(),
        "Utility Functions": test_utility_functions(),
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
        print("✅ All query helper tests passed!")
        print("=" * 60)
        return 0
    else:
        print("❌ Some query helper tests failed")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
