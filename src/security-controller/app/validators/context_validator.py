"""
Context Validator - Step 4 of Validation Pipeline

Validates tool call sequences to ensure required tools are called first.
Simple MVP implementation checks presence in last 10 tools.

Requirements: LLD 03 Section 3.4, 8.1
"""
import logging
import os
from typing import Dict, List

import yaml

from app.api.models import ValidationRequest, ValidationResult

logger = logging.getLogger(__name__)


class ContextValidator:
    """
    Validates tool call sequences.

    MVP Limitations:
    - Only checks presence (not order)
    - Only checks last 10 tools in session history
    - Does NOT match parameters between tools

    Example:
    - process_refund requires check_order to be called first
    - reverse_refund requires process_refund to be called first
    """

    def __init__(self, config_path: str = None):
        # Load requirements from config/tool_requirements.yaml
        self.requirements = self._load_requirements(config_path)
        logger.info(f"Loaded {len(self.requirements)} tool requirements")

    def _load_requirements(self, config_path: str = None) -> Dict:
        """
        Load tool requirements from config/tool_requirements.yaml

        Args:
            config_path: Path to config file (optional)

        Returns:
            Dict mapping tool_name to required tools
        """
        try:
            # Default path relative to project root
            if config_path is None:
                # Get project root (4 levels up from this file)
                current_dir = os.path.dirname(os.path.abspath(__file__))
                project_root = os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
                )
                config_path = os.path.join(project_root, "config", "tool_requirements.yaml")

            if not os.path.exists(config_path):
                logger.warning(
                    f"Tool requirements config not found: {config_path}. Using empty requirements."
                )
                return {}

            with open(config_path, "r") as f:
                requirements = yaml.safe_load(f) or {}

            logger.debug(f"Loaded tool requirements from {config_path}")
            return requirements

        except Exception as e:
            logger.exception(f"Error loading tool requirements: {e}")
            return {}

    async def validate_sequence(
        self, session: Dict, request: ValidationRequest
    ) -> ValidationResult:
        """
        Validate that required tools were called before this tool.

        Args:
            session: Session data with tool_history
            request: Validation request

        Returns:
            ValidationResult with decision (ALLOW/DENY)
        """
        try:
            tool_name = request.tool_name

            # Check if tool has requirements
            if tool_name not in self.requirements:
                logger.debug(f"No requirements for tool: {tool_name}")
                return ValidationResult(
                    decision="ALLOW",
                    reason="No sequence requirements",
                    should_deny=False,
                )

            # Extract called tools from session history (last 10)
            tool_history = session.get("tool_history", [])
            called_tools = [item["tool_name"] for item in tool_history[-10:]]

            logger.debug(
                f"Checking sequence for {tool_name}. History (last 10): {called_tools}"
            )

            # Check if ALL required tools were called
            required_tools = self.requirements[tool_name].get("requires", [])
            missing_tools = []

            for required in required_tools:
                if required not in called_tools:
                    missing_tools.append(required)

            if missing_tools:
                logger.warning(
                    f"Sequence violation: {tool_name} requires {missing_tools} "
                    f"but not found in history"
                )
                return ValidationResult(
                    decision="DENY",
                    reason=f"Must call '{missing_tools[0]}' before '{tool_name}'",
                    violation_type="SEQUENCE_VIOLATION",
                    penalty=-15,
                    should_deny=True,
                )

            # All required tools present
            logger.debug(f"Sequence validation passed for {tool_name}")
            return ValidationResult(
                decision="ALLOW",
                reason="All required tools called",
                should_deny=False,
            )

        except Exception as e:
            logger.exception(f"Context validation error: {e}")
            # Fail-secure: deny on errors
            return ValidationResult(
                decision="DENY",
                reason="Context validation error",
                violation_type="SYSTEM_ERROR",
                penalty=-10,
                should_deny=True,
            )
