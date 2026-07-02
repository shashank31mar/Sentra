"""
Unit Tests for PolicyValidator

Tests schema validation and business rules validation.
Reference: Workstream 11 - LLD 11 Section 5.1

Target: >80% coverage on policy_validator.py
"""

import pytest
from unittest.mock import Mock, patch, PropertyMock
from pydantic import ValidationError


@pytest.fixture
def mock_policy_validator():
    """Create PolicyValidator with mocked AWS resources.

    Two seams changed since these tests were written (Cedar cutover CT11 + the
    workstream-T9 registry refactor):

    * `agent_registry` is now a READ-ONLY @property
      (returns self.dynamodb.Table(tenancy.table_name('agent_registry'))), so
      `validator.agent_registry = Mock()` raises "property has no setter". We
      patch the PROPERTY with a PropertyMock and expose its return_value as
      `validator.agent_registry` so tests can drive get_item like before.
    * `tool_registry` is still a plain attribute set in __init__ → assignable.

    Cedar is DISABLED for this fixture so we exercise the deterministic
    schema + agent + duplicate + semver path. Cedar schema validation is covered
    by the dedicated cedar test suite (app/validators/cedar/...); a unit test of
    the pure validator must not depend on the Cedar generator/evaluator being
    wired up. `settings.cedar_enabled` defaults to False under system python3
    (no CEDAR_ENABLED env), but we patch it explicitly so the test is
    deterministic regardless of ambient env.
    """
    with patch('app.services.policy_validator.boto3'):
        from app.services.policy_validator import PolicyValidator
        validator = PolicyValidator()

        # Patch the read-only agent_registry property; the returned Mock is what
        # the code's `self.agent_registry.get_item(...)` calls hit.
        agent_registry_mock = Mock()
        patcher = patch.object(
            PolicyValidator, 'agent_registry',
            new_callable=PropertyMock, return_value=agent_registry_mock,
        )
        patcher.start()

        # Existing test bodies read `mock_policy_validator.agent_registry.get_item`.
        # With the property patched, `validator.agent_registry` returns
        # `agent_registry_mock` (the PropertyMock's return_value) — same object
        # the production code hits via `self.agent_registry.get_item(...)`. No
        # instance assignment needed (and it would fail: the property has no
        # setter).

        # tool_registry is a plain attribute → still assignable.
        validator.tool_registry = Mock()

        # Force cedar OFF for a deterministic schema/agent/dup/semver path.
        with patch('app.services.policy_validator.settings') as mock_settings:
            mock_settings.cedar_enabled = False
            mock_settings.aws_region = 'us-east-1'
            try:
                yield validator
            finally:
                patcher.stop()


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

        # Verify agent registry was checked. The lookup Key is now built by the
        # tenancy helper (tenancy.item_key('agent_id', agent_id)) — v1 →
        # {'agent_id': ...}, v2 → {'tenant_id': ..., 'agent_id': ...}. Assert
        # against the real helper so this stays correct if TENANCY_V2_ENABLED
        # flips, rather than hard-coding the v1 shape.
        from app.utils import tenancy
        mock_policy_validator.agent_registry.get_item.assert_called_once_with(
            Key=tenancy.item_key('agent_id', 'test-agent')
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

    def test_validate_policy_tool_not_found_is_warning_only(self, mock_policy_validator, valid_policy_data):
        """An unknown tool is WARNING-ONLY and does NOT block the policy.

        CONTRACT CHANGE: the old test asserted an unknown tool made the policy
        invalid ("query_orders" ... "not found in registry"). policy_validator.py
        step 3 now only `logger.warning(...)` on a missing tool ("policy will
        still be accepted") — it does NOT append an error and does NOT flip
        is_valid. We deliberately update this to assert the CURRENT warning-only
        contract: the policy stays valid purely on tool grounds.
        """
        # Agent exists; second tool (query_orders) does NOT exist.
        mock_policy_validator.agent_registry.get_item.return_value = {
            'Item': {'agent_id': 'test-agent'}
        }
        mock_policy_validator.tool_registry.get_item.side_effect = [
            {'Item': {'tool_id': 'query_customers'}},  # First tool exists
            {}  # Second tool doesn't exist → warning only, no block
        ]

        # Execute
        is_valid, errors = mock_policy_validator.validate_policy(valid_policy_data)

        # Assert: an unknown tool no longer blocks; policy stays valid and no
        # tool-not-found error is surfaced.
        assert is_valid is True
        assert errors is None

    def test_validate_policy_inert_rule_string_does_not_block(self, mock_policy_validator, valid_policy_data):
        """A syntactically-broken `policies[].rule` string does NOT block.

        CONTRACT CHANGE (CT11): the legacy `compile(rule, 'eval')` syntax check
        was REMOVED. The `policies[].rule` strings are inert/decorative now —
        real authorization is Cedar. The old test asserted an "Invalid rule
        expression" error for a broken rule; that error no longer exists. We
        deliberately assert the CURRENT contract: even a rule that would fail a
        Python `compile()` (e.g. an unbalanced paren) is accepted, because the
        rule string is never compiled anymore. (Cedar is disabled in this
        fixture, so no Cedar-path errors mask this.)
        """
        mock_policy_validator.agent_registry.get_item.return_value = {
            'Item': {'agent_id': 'test-agent'}
        }
        mock_policy_validator.tool_registry.get_item.return_value = {
            'Item': {'tool_id': 'query_customers'}
        }

        # A string that would have failed the removed compile() check.
        valid_policy_data['policies'][0]['rule'] = "query_limit <= 1000 AND ("

        # Execute
        is_valid, errors = mock_policy_validator.validate_policy(valid_policy_data)

        # Assert: no rule-syntax error is produced; the policy is valid.
        assert is_valid is True
        assert errors is None

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

    def test_validate_policy_agent_missing_plus_duplicate_ids(self, mock_policy_validator, valid_policy_data):
        """Validation accumulates the still-blocking errors (agent + duplicate).

        CONTRACT CHANGE: the old test expected >=3 errors made of
        agent-not-found + 2 tools-not-found + invalid-rule. Post-CT11 the only
        blocking business-rule errors are agent-not-found, DUPLICATE policy_id,
        and semver — tool-not-found is warning-only and the rule syntax check is
        gone. So instead of relying on removed error sources, we combine two
        still-blocking causes (missing agent + duplicate policy_id) and assert
        both errors are surfaced together (accumulation still works).
        """
        # Agent doesn't exist; tools don't exist (warning only, no error).
        mock_policy_validator.agent_registry.get_item.return_value = {}
        mock_policy_validator.tool_registry.get_item.return_value = {}

        # Add a duplicate policy_id (still a blocking error).
        valid_policy_data['policies'].append({
            "policy_id": "pol-001",  # Duplicate of the existing one!
            "name": "Another Rule",
            "rule": "parameter <= 500",
            "action": "DENY",
            "severity": "medium",
            "enabled": True
        })

        # Execute
        is_valid, errors = mock_policy_validator.validate_policy(valid_policy_data)

        # Assert: both still-blocking errors are present (accumulated).
        assert is_valid is False
        assert errors is not None
        assert any("not found in registry" in err for err in errors)   # agent
        assert any("Duplicate policy_id" in err for err in errors)     # dup
        # No tool-not-found and no rule-syntax error should appear anymore.
        assert not any("Invalid rule expression" in err for err in errors)


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
