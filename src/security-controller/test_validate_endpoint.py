#!/usr/bin/env python3
"""
Quick test script for /validate endpoint
"""
import asyncio
import sys
from app.api.routes import validate_tool_call
from app.api.models import ValidationRequest

async def test_validate():
    """Test the validate endpoint"""
    
    # Test 1: Basic ALLOW request
    print("Test 1: Basic validation request (should ALLOW)")
    print("-" * 60)
    
    request = ValidationRequest(
        request_id="test-req-001",
        session_id="test-session-001",
        agent_id="customer-query-agent",
        tool_name="query_customers",
        tool_params={"query": "SELECT * FROM customers WHERE state='CA' LIMIT 10"},
        user_input="Show customers from California",
        timestamp="2025-01-18T10:30:00Z",
        operation_type="READ"
    )
    
    response = await validate_tool_call(request)
    print(f"Decision: {response['decision']}")
    print(f"Reason: {response['reason']}")
    print(f"Trust Score: {response['trust_score']}")
    print(f"Latency: {response['latency_ms']:.2f}ms")
    print(f"Action ID: {response.get('action_id', 'None')}")
    print()
    
    # Test 2: Reversible action (should generate action_id)
    print("Test 2: Reversible action (process_refund)")
    print("-" * 60)
    
    request2 = ValidationRequest(
        request_id="test-req-002",
        session_id="test-session-001",
        agent_id="payment-agent",
        tool_name="process_refund",
        tool_params={"order_id": "ORD-123", "amount": 5000.0},
        user_input="Process refund for order ORD-123",
        timestamp="2025-01-18T10:31:00Z",
        operation_type="WRITE"
    )
    
    response2 = await validate_tool_call(request2)
    print(f"Decision: {response2['decision']}")
    print(f"Reason: {response2['reason']}")
    print(f"Trust Score: {response2['trust_score']}")
    print(f"Latency: {response2['latency_ms']:.2f}ms")
    print(f"Action ID: {response2.get('action_id', 'None')}")
    print()
    
    # Test 3: Multiple requests to test trust score increment
    print("Test 3: Multiple requests (testing trust score updates)")
    print("-" * 60)
    
    for i in range(3):
        request3 = ValidationRequest(
            request_id=f"test-req-{100+i}",
            session_id="test-session-001",
            agent_id="customer-query-agent",
            tool_name="query_orders",
            tool_params={},
            user_input="Show orders",
            timestamp="2025-01-18T10:32:00Z",
            operation_type="READ"
        )
        
        response3 = await validate_tool_call(request3)
        print(f"Request {i+1}: Trust Score = {response3['trust_score']:.1f}, "
              f"Decision = {response3['decision']}")
    
    print()
    print("✅ All tests completed!")

if __name__ == "__main__":
    asyncio.run(test_validate())
