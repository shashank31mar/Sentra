"""
Unit Tests for PolicyValidator

Tests schema validation and business rules validation.
Reference: Workstream 11 - LLD 11 Section 5.1

Target: >80% coverage on policy_validator.py
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pydantic import ValidationError


@pytest.fixture
def mock_policy_validator():
    """Create PolicyValidator with mocked AWS resources."""
    with patch('app.services.policy_validator.boto3'):
        from app.services.policy_validator import PolicyValidator
        validator = PolicyValidator()

        # Mock DynamoDB tables
        validator.agent_registry = Mock()
        validator.tool_registry = Mock()

        return validator


@pytest.fixture
def valid_policy_data():
    """Valid policy data for testing."""
    return {
        "schema_version": "v1",
        "policy_id": "agent-config-test-agent",
        "agent_id": "test-agent",
        "name": "Test Policy",
        "version": "1.0.0",
        "status": "active",
        "description": "Test policy",
        "allowed_tools": ["query_customers", "query_orders"],
        "policies": [
            {
                "policy_id": "pol-001",
                "name": "Max Query Limit",
                "description": "Limit queries",
                "rule": "query_limit <= 1000",
                "action": "DENY",
                "severity": "high",
                "enabled": True
            }
        ],
        "created_at": "2025-12-03T10:00:00Z",
        "created_by": "test@example.com"
    }


class TestPolicyValidatorSuccess:
    """Tests for successful validation."""

    def test_validate_policy_all_valid(self, mock_policy_validator, valid_policy_data):
        """Test validation with all valid data."""
        # Setup mocks - agent and tools exist
        mock_policy_validator.agent_registry.get_item.return_value = {
            'Item': {'agent_id': 'test-agent'}
        }
        mock_policy_validator.tool_registry.get_item.side_effect = [
            {'Item': {'tool_id': 'query_customers'}},
            {'Item': {'tool_id': 'query_orders'}}
        ]

        # Execute
        is_valid, errors = mock_policy_validator.validate_policy(valid_policy_data)

        # Assert
        assert is_valid is True
        assert errors is None

        # Verify agent registry was checked
        mock_policy_validator.agent_registry.get_item.assert_called_once_with(
            Key={'agent_id': 'test-agent'}
        )

        # Verify tool registry was checked for each tool
        assert mock_policy_validator.tool_registry.get_item.call_count == 2


class TestPolicyValidatorSchemaFailures:
    """Tests for schema validation failures."""

    def test_validate_policy_missing_required_field(self, mock_policy_validator):
        """Test validation with missing required field."""
        invalid_data = {
            "schema_version": "v1",
            # Missing agent_id
            "name": "Test Policy",
            "version": "1.0.0"
        }

        # Execute
        is_valid, errors = mock_policy_validator.validate_policy(invalid_data)

        # Assert
        assert is_valid is False
        assert errors is not None
        assert len(errors) > 0
        assert "Schema error" in errors[0] or "Field required" in errors[0]

    def test_validate_policy_invalid_version_format(self, mock_policy_validator, valid_policy_data):
        """Test validation with invalid version format."""
        # Invalid semver format
        valid_policy_data['version'] = "1.0"

        # Execute
        is_valid, errors = mock_policy_validator.validate_policy(valid_policy_data)

        # Assert
        assert is_valid is False
        assert errors is not None

    def test_validate_policy_empty_allowed_tools(self, mock_policy_validator, valid_policy_data):
        """Test validation with empty allowed_tools array."""
        valid_policy_data['allowed_tools'] = []

        # Execute
        is_valid, errors = mock_policy_validator.validate_policy(valid_policy_data)

        # Assert
        assert is_valid is False
        assert errors is not None

    def test_validate_policy_empty_policies_array(self, mock_policy_validator, valid_policy_data):
        """Test validation with empty policies array."""
        valid_policy_data['policies'] = []

        # Execute
        is_valid, errors = mock_policy_validator.validate_policy(valid_policy_data)

        # Assert
        assert is_valid is False
        assert errors is not None


class TestPolicyValidatorBusinessRules:
    """Tests for business rule validation."""

    def test_validate_policy_agent_not_found(self, mock_policy_validator, valid_policy_data):
        """Test validation when agent doesn't exist."""
        # Setup mock - agent not found
        mock_policy_validator.agent_registry.get_item.return_value = {}

        # Execute
        is_valid, errors = mock_policy_validator.validate_policy(valid_policy_data)

        # Assert
        assert is_valid is False
        assert errors is not None
        assert any("not found in registry" in err for err in errors)
        assert any("test-agent" in err for err in errors)

    def test_validate_policy_tool_not_found(self, mock_policy_validator, valid_policy_data):
        """Test validation when tool doesn't exist."""
        # Setup mocks - agent exists, but tool doesn't
        mock_policy_validator.agent_registry.get_item.return_value = {
            'Item': {'agent_id': 'test-agent'}
        }
        mock_policy_validator.tool_registry.get_item.side_effect = [
            {'Item': {'tool_id': 'query_customers'}},  # First tool exists
            {}  # Second tool doesn't exist
        ]

        # Execute
        is_valid, errors = mock_policy_validator.validate_policy(valid_policy_data)

        # Assert
        assert is_valid is False
        assert errors is not None
        assert any("query_orders" in err for err in errors)
        assert any("not found in registry" in err for err in errors)

    def test_validate_policy_invalid_rule_expression(self, mock_policy_validator, valid_policy_data):
        """Test validation with invalid Python rule expression."""
        # Setup mocks - agent and tools exist
        mock_policy_validator.agent_registry.get_item.return_value = {
            'Item': {'agent_id': 'test-agent'}
        }
        mock_policy_validator.tool_registry.get_item.return_value = {
            'Item': {'tool_id': 'query_customers'}
        }

        # Invalid rule expression (syntax error)
        valid_policy_data['policies'][0]['rule'] = "query_limit <= 1000 AND ("

        # Execute
        is_valid, errors = mock_policy_validator.validate_policy(valid_policy_data)

        # Assert
        assert is_valid is False
        assert errors is not None
        assert any("Invalid rule expression" in err for err in errors)

    def test_validate_policy_duplicate_policy_ids(self, mock_policy_validator, valid_policy_data):
        """Test validation with duplicate policy IDs."""
        # Setup mocks
        mock_policy_validator.agent_registry.get_item.return_value = {
            'Item': {'agent_id': 'test-agent'}
        }
        mock_policy_validator.tool_registry.get_item.return_value = {
            'Item': {'tool_id': 'query_customers'}
        }

        # Add duplicate policy ID
        valid_policy_data['policies'].append({
            "policy_id": "pol-001",  # Duplicate!
            "name": "Another Rule",
            "rule": "parameter <= 500",
            "action": "DENY",
            "severity": "medium",
            "enabled": True
        })

        # Execute
        is_valid, errors = mock_policy_validator.validate_policy(valid_policy_data)

        # Assert
        assert is_valid is False
        assert errors is not None
        assert any("Duplicate policy_id" in err for err in errors)


class TestPolicyValidatorComplexRules:
    """Tests for complex rule validation scenarios."""

    def test_validate_policy_complex_rule_valid(self, mock_policy_validator, valid_policy_data):
        """Test validation with complex but valid rule."""
        # Setup mocks
        mock_policy_validator.agent_registry.get_item.return_value = {
            'Item': {'agent_id': 'test-agent'}
        }
        mock_policy_validator.tool_registry.get_item.return_value = {
            'Item': {'tool_id': 'query_customers'}
        }

        # Complex valid rule
        valid_policy_data['policies'][0]['rule'] = "(amount > 1000 and status == 'pending') or priority == 'high'"

        # Execute
        is_valid, errors = mock_policy_validator.validate_policy(valid_policy_data)

        # Assert
        assert is_valid is True
        assert errors is None

    def test_validate_policy_rule_with_functions(self, mock_policy_validator, valid_policy_data):
        """Test validation with rule containing Python functions."""
        # Setup mocks
        mock_policy_validator.agent_registry.get_item.return_value = {
            'Item': {'agent_id': 'test-agent'}
        }
        mock_policy_validator.tool_registry.get_item.return_value = {
            'Item': {'tool_id': 'query_customers'}
        }

        # Rule with functions
        valid_policy_data['policies'][0]['rule'] = "len(items) > 100 and max(values) < 1000"

        # Execute
        is_valid, errors = mock_policy_validator.validate_policy(valid_policy_data)

        # Assert
        assert is_valid is True
        assert errors is None

    def test_validate_policy_multiple_errors(self, mock_policy_validator, valid_policy_data):
        """Test validation returns multiple errors."""
        # Setup mocks - agent doesn't exist, tools don't exist
        mock_policy_validator.agent_registry.get_item.return_value = {}
        mock_policy_validator.tool_registry.get_item.return_value = {}

        # Also add invalid rule
        valid_policy_data['policies'][0]['rule'] = "invalid syntax (("

        # Execute
        is_valid, errors = mock_policy_validator.validate_policy(valid_policy_data)

        # Assert
        assert is_valid is False
        assert errors is not None
        assert len(errors) >= 3  # Agent not found, 2 tools not found, invalid rule


class TestPolicyValidatorEdgeCases:
    """Tests for edge cases."""

    def test_validate_policy_none_rule(self, mock_policy_validator, valid_policy_data):
        """Test validation when rule is None (optional field)."""
        # Setup mocks
        mock_policy_validator.agent_registry.get_item.return_value = {
            'Item': {'agent_id': 'test-agent'}
        }
        mock_policy_validator.tool_registry.get_item.return_value = {
            'Item': {'tool_id': 'query_customers'}
        }

        # Set rule to None
        valid_policy_data['policies'][0]['rule'] = None

        # Execute
        is_valid, errors = mock_policy_validator.validate_policy(valid_policy_data)

        # Assert - should be valid (rule is optional)
        assert is_valid is True
        assert errors is None

    def test_validate_policy_empty_rule_string(self, mock_policy_validator, valid_policy_data):
        """Test validation with empty rule string."""
        # Setup mocks
        mock_policy_validator.agent_registry.get_item.return_value = {
            'Item': {'agent_id': 'test-agent'}
        }
        mock_policy_validator.tool_registry.get_item.return_value = {
            'Item': {'tool_id': 'query_customers'}
        }

        # Empty rule
        valid_policy_data['policies'][0]['rule'] = ""

        # Execute
        is_valid, errors = mock_policy_validator.validate_policy(valid_policy_data)

        # Assert - should be valid (rule can be empty)
        assert is_valid is True
        assert errors is None

    def test_validate_policy_single_tool(self, mock_policy_validator, valid_policy_data):
        """Test validation with single tool."""
        # Setup mocks
        mock_policy_validator.agent_registry.get_item.return_value = {
            'Item': {'agent_id': 'test-agent'}
        }
        mock_policy_validator.tool_registry.get_item.return_value = {
            'Item': {'tool_id': 'query_customers'}
        }

        # Single tool
        valid_policy_data['allowed_tools'] = ['query_customers']

        # Execute
        is_valid, errors = mock_policy_validator.validate_policy(valid_policy_data)

        # Assert
        assert is_valid is True
        assert errors is None

    def test_validate_policy_many_tools(self, mock_policy_validator, valid_policy_data):
        """Test validation with many tools."""
        # Setup mocks
        mock_policy_validator.agent_registry.get_item.return_value = {
            'Item': {'agent_id': 'test-agent'}
        }
        mock_policy_validator.tool_registry.get_item.return_value = {
            'Item': {'tool_id': 'tool'}
        }

        # Many tools
        valid_policy_data['allowed_tools'] = [f'tool_{i}' for i in range(20)]

        # Execute
        is_valid, errors = mock_policy_validator.validate_policy(valid_policy_data)

        # Assert
        assert is_valid is True
        assert errors is None
        assert mock_policy_validator.tool_registry.get_item.call_count == 20
