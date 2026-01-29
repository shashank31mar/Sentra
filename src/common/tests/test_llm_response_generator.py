"""
Unit tests for LLM Response Generator
Sentra MVP - Workstream 9 - Milestone 1
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json

from common.llm_response_generator import (
    LLMResponseGenerator,
    ResponseTemplate,
    generate_nlp_response
)


# ==================== Fixtures ====================

@pytest.fixture
def mock_bedrock_client():
    """Mock Bedrock runtime client"""
    with patch('boto3.client') as mock_client:
        mock_bedrock = MagicMock()

        # Mock successful response
        mock_response = {
            'body': MagicMock()
        }
        mock_response['body'].read.return_value = json.dumps({
            'content': [{'text': 'I found 2 customers from California.'}]
        }).encode('utf-8')

        mock_bedrock.invoke_model.return_value = mock_response
        mock_client.return_value = mock_bedrock

        yield mock_client


@pytest.fixture
def llm_generator(mock_bedrock_client):
    """LLM generator instance with mocked Bedrock"""
    return LLMResponseGenerator()


# ==================== Initialization Tests ====================

def test_initialization_default_values(mock_bedrock_client):
    """Test LLM generator initializes with default values"""
    gen = LLMResponseGenerator()

    assert gen.model_id == 'anthropic.claude-sonnet-4-5-20250929-v1:0'
    assert gen.fallback_model_id == 'anthropic.claude-haiku-4-5-20251001-v1:0'
    assert gen.region_name == 'us-east-1'


def test_initialization_custom_values(mock_bedrock_client):
    """Test LLM generator initializes with custom values"""
    gen = LLMResponseGenerator(
        model_id='custom-model',
        fallback_model_id='custom-fallback',
        region_name='us-west-2'
    )

    assert gen.model_id == 'custom-model'
    assert gen.fallback_model_id == 'custom-fallback'
    assert gen.region_name == 'us-west-2'


# ==================== Response Generation Tests ====================

def test_generate_customer_list_response(llm_generator):
    """Test generating customer list response"""
    customers = [
        {'customer_id': 'cust-001', 'name': 'John Doe', 'email': 'john@example.com'},
        {'customer_id': 'cust-002', 'name': 'Jane Smith', 'email': 'jane@example.com'}
    ]

    response = llm_generator.generate_response(
        user_query="Show customers from CA",
        data=customers,
        template_type=ResponseTemplate.CUSTOMER_LIST
    )

    assert isinstance(response, str)
    assert len(response) > 0


def test_generate_order_details_response(llm_generator):
    """Test generating order details response"""
    order = {
        'order_id': 'ORD-123',
        'amount': 50.0,
        'status': 'completed',
        'items': [{'name': 'Widget', 'quantity': 2}]
    }

    response = llm_generator.generate_response(
        user_query="Show order details",
        data=order,
        template_type=ResponseTemplate.ORDER_DETAILS
    )

    assert isinstance(response, str)
    assert len(response) > 0


def test_generate_denial_response(llm_generator):
    """Test generating denial response"""
    validation_result = {
        'decision': 'DENY',
        'reason': 'Exceeds max_refund_amount limit of $5,000',
        'threat_type': 'POLICY_VIOLATION',
        'violated_policy': 'max_refund_amount'
    }

    response = llm_generator.generate_denial_response(
        user_query="Process refund for $100,000",
        validation_result=validation_result
    )

    assert isinstance(response, str)
    assert len(response) > 0


# ==================== Fallback Response Tests ====================

def test_fallback_response_for_empty_list():
    """Test fallback response for empty list"""
    gen = LLMResponseGenerator()
    fallback = gen._fallback_response([], ResponseTemplate.CUSTOMER_LIST)

    assert fallback == "No results found."


def test_fallback_response_for_small_list():
    """Test fallback response for list with <=5 items"""
    gen = LLMResponseGenerator()
    data = [{'id': i} for i in range(3)]
    fallback = gen._fallback_response(data, ResponseTemplate.CUSTOMER_LIST)

    assert "Found 3 results" in fallback


def test_fallback_response_for_large_list():
    """Test fallback response for list with >5 items"""
    gen = LLMResponseGenerator()
    data = [{'id': i} for i in range(10)]
    fallback = gen._fallback_response(data, ResponseTemplate.CUSTOMER_LIST)

    assert "Found 10 results" in fallback
    assert "and 5 more" in fallback


def test_fallback_response_for_denial():
    """Test fallback response for denial"""
    gen = LLMResponseGenerator()
    validation_result = {'reason': 'SQL injection detected'}
    fallback = gen._fallback_response(validation_result, ResponseTemplate.DENIAL)

    assert "⚠️ Request blocked" in fallback
    assert "SQL injection detected" in fallback


# ==================== Error Handling Tests ====================

def test_fallback_model_used_on_primary_failure():
    """Test that fallback model is used when primary fails"""
    with patch('boto3.client') as mock_client:
        mock_bedrock = MagicMock()

        # Primary model fails
        mock_bedrock.invoke_model.side_effect = [
            Exception("Primary model unavailable"),
            # Fallback succeeds
            {
                'body': MagicMock(
                    read=lambda: json.dumps({
                        'content': [{'text': 'Fallback response'}]
                    }).encode('utf-8')
                )
            }
        ]

        mock_client.return_value = mock_bedrock

        gen = LLMResponseGenerator()
        response = gen.generate_response(
            user_query="test",
            data={"test": "data"},
            template_type=ResponseTemplate.GENERIC
        )

        # Should return fallback model's response
        assert response == "Fallback response"
        assert mock_bedrock.invoke_model.call_count == 2


def test_structured_fallback_on_all_failures():
    """Test structured fallback when both models fail"""
    with patch('boto3.client') as mock_client:
        mock_bedrock = MagicMock()

        # Both models fail
        mock_bedrock.invoke_model.side_effect = Exception("All models unavailable")

        mock_client.return_value = mock_bedrock

        gen = LLMResponseGenerator()
        data = [{'id': 1}, {'id': 2}]
        response = gen.generate_response(
            user_query="test",
            data=data,
            template_type=ResponseTemplate.CUSTOMER_LIST
        )

        # Should return structured fallback
        assert "Found 2 results" in response


# ==================== Prompt Building Tests ====================

def test_customer_list_prompt_building():
    """Test customer list prompt is built correctly"""
    gen = LLMResponseGenerator()
    prompt = gen._build_customer_list_prompt(
        "Show customers",
        json.dumps([{'name': 'John'}])
    )

    assert "Show customers" in prompt
    assert "John" in prompt
    assert "bullet points" in prompt.lower()


def test_denial_prompt_building():
    """Test denial prompt is built correctly"""
    gen = LLMResponseGenerator()
    validation_result = {
        'decision': 'DENY',
        'reason': 'Policy violation',
        'threat_type': 'INJECTION'
    }

    prompt = gen._build_denial_prompt(
        "malicious query",
        validation_result
    )

    assert "malicious query" in prompt
    assert "Policy violation" in prompt
    assert "blocked" in prompt.lower()


# ==================== Module-level Helper Tests ====================

def test_generate_nlp_response_helper(mock_bedrock_client):
    """Test module-level helper function"""
    response = generate_nlp_response(
        user_query="test query",
        data={"test": "data"},
        template_type="generic"
    )

    assert isinstance(response, str)
    assert len(response) > 0


# ==================== Template Type Tests ====================

def test_template_type_enum_conversion():
    """Test string template types are converted to enum"""
    gen = LLMResponseGenerator()

    # Should convert string to enum
    response = gen.generate_response(
        user_query="test",
        data=[],
        template_type="customer_list"  # String instead of enum
    )

    assert isinstance(response, str)


def test_invalid_template_type_uses_generic():
    """Test invalid template type falls back to generic"""
    gen = LLMResponseGenerator()

    # Invalid template should use generic
    response = gen.generate_response(
        user_query="test",
        data={"test": "data"},
        template_type="invalid_template"
    )

    assert isinstance(response, str)


# ==================== Integration-style Tests ====================

def test_full_workflow_customer_query():
    """Test full workflow for customer query"""
    with patch('boto3.client') as mock_client:
        mock_bedrock = MagicMock()
        mock_bedrock.invoke_model.return_value = {
            'body': MagicMock(
                read=lambda: json.dumps({
                    'content': [{'text': 'I found 2 customers: John Doe and Jane Smith.'}]
                }).encode('utf-8')
            )
        }
        mock_client.return_value = mock_bedrock

        gen = LLMResponseGenerator()

        customers = [
            {'name': 'John Doe', 'email': 'john@example.com'},
            {'name': 'Jane Smith', 'email': 'jane@example.com'}
        ]

        response = gen.generate_response(
            user_query="Show customers from California",
            data=customers,
            template_type=ResponseTemplate.CUSTOMER_LIST,
            max_tokens=500,
            temperature=0.7
        )

        assert "John Doe" in response or "customers" in response.lower()
        assert isinstance(response, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
