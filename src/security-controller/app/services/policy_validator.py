"""
Policy Validator - Schema and business rule validation for agent policies.
"""
import boto3
import logging
from typing import Dict, List, Optional, Tuple
from pydantic import ValidationError

logger = logging.getLogger(__name__)


class PolicyValidator:
    """Validates policy documents (schema + business rules)."""

    def __init__(self):
        self.dynamodb = boto3.resource('dynamodb')
        self.agent_registry = self.dynamodb.Table('sentra-agent-registry')
        self.tool_registry = self.dynamodb.Table('sentra-tool-registry')

    def validate_policy(self, policy_data: Dict) -> Tuple[bool, Optional[List[str]]]:
        """
        Validate policy against schema and business rules.

        Args:
            policy_data: Policy document dict

        Returns:
            (is_valid, errors) - Tuple of boolean and optional error list
        """
        errors = []

        # 1. Schema validation (Pydantic)
        try:
            # Import here to avoid circular imports
            from schemas.policy_schema import AgentPolicyDocument
            policy = AgentPolicyDocument(**policy_data)
        except ValidationError as e:
            for error in e.errors():
                field = ' -> '.join(str(loc) for loc in error['loc'])
                errors.append(f"Schema error at {field}: {error['msg']}")
            return False, errors
        except Exception as e:
            errors.append(f"Schema validation failed: {str(e)}")
            return False, errors

        # 2. Agent exists?
        if not self._agent_exists(policy_data.get('agent_id')):
            errors.append(f"Agent '{policy_data.get('agent_id')}' not found in registry")

        # 3. Tools exist? (warning only, don't block)
        for tool_id in policy_data.get('allowed_tools', []):
            if not self._tool_exists(tool_id):
                logger.warning(f"Tool '{tool_id}' not found in registry (policy will still be accepted)")

        # 4. Policy rules are valid Python expressions?
        for i, rule in enumerate(policy_data.get('policies', [])):
            rule_expr = rule.get('rule')
            if rule_expr:
                if not self._is_valid_rule_expression(rule_expr):
                    errors.append(
                        f"Invalid rule expression at policies[{i}]: '{rule_expr}' "
                        f"(must be valid Python expression)"
                    )

        # 5. No duplicate policy IDs within document
        policy_ids = [p.get('policy_id') for p in policy_data.get('policies', [])]
        if len(policy_ids) != len(set(policy_ids)):
            errors.append("Duplicate policy_id found within policies array")

        # 6. Version format (semver)
        version = policy_data.get('version', '')
        if not self._is_valid_semver(version):
            errors.append(f"Invalid version format '{version}' (must be semver: X.Y.Z)")

        return (len(errors) == 0), (errors if errors else None)

    def _agent_exists(self, agent_id: str) -> bool:
        """Check if agent exists in registry."""
        try:
            response = self.agent_registry.get_item(Key={'agent_id': agent_id})
            return 'Item' in response
        except Exception as e:
            logger.error(f"Error checking agent existence: {e}")
            return False

    def _tool_exists(self, tool_id: str) -> bool:
        """Check if tool exists in registry."""
        try:
            response = self.tool_registry.get_item(Key={'tool_id': tool_id})
            return 'Item' in response
        except Exception as e:
            logger.error(f"Error checking tool existence: {e}")
            return False

    def _is_valid_rule_expression(self, rule: str) -> bool:
        """Check if rule is a valid Python expression (syntax only, no execution)."""
        try:
            compile(rule, '<string>', 'eval')
            return True
        except SyntaxError:
            return False
        except Exception:
            return False

    def _is_valid_semver(self, version: str) -> bool:
        """Check if version follows semver format (X.Y.Z)."""
        import re
        pattern = r'^\d+\.\d+\.\d+$'
        return bool(re.match(pattern, version))
