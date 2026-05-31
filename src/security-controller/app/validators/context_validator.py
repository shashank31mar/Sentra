"""
Context Validator - Step 4 of Validation Pipeline

Validates tool call sequences to ensure required tools are called first.
Single-cloud sequence checks use config/tool_requirements.yaml; cross-cloud
sequence checks are driven by `cross_cloud_dependencies` on the agent policy
(Workstream 15 — see LLD 15 §4.5).

Requirements: LLD 03 Section 3.4, 8.1; LLD 15 §4.5
"""
import logging
import os
import time
from typing import Any, Dict, List, Optional

import yaml

from app.api.models import ValidationRequest, ValidationResult
from app.combiners import Source
from app.validators._signal_stamp import stamps

logger = logging.getLogger(__name__)


class ContextValidator:
    """
    Validates tool call sequences.

    Single-cloud MVP behavior:
    - Checks presence (not order) of required tools in last 10 history entries
    - Loaded from config/tool_requirements.yaml

    Cross-cloud (Workstream 15):
    - Honors `cross_cloud_dependencies` on the agent policy.
    - For each dep where the requested tool is in `required_before`, requires a
      matching prior tool call by the named target_agent within max_age_seconds.
    - DENY with violation_type=CROSS_CLOUD_SEQUENCE_VIOLATION when unmet.
    - Requires a `policy_engine` injection to look up the policy; if absent,
      cross-cloud checks are silently skipped (degrades to single-cloud behavior).

    Example (Scenario S3 — Swiggy egg-fraud, cross-cloud):
    - process_refund on sentra-mvp-customer-service-agent requires
      verify_image_authenticity on azure-verification-agent within 300s.
    """

    def __init__(self, config_path: str = None, policy_engine: Optional[Any] = None):
        # Load single-cloud requirements from config/tool_requirements.yaml
        self.requirements = self._load_requirements(config_path)
        # Workstream 15: optional policy_engine for cross-cloud lookups
        self.policy_engine = policy_engine
        logger.info(
            f"Loaded {len(self.requirements)} tool requirements "
            f"(cross_cloud_enabled={'yes' if policy_engine else 'no'})"
        )

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

    @stamps(Source.SENTRA_CONTEXT)
    async def validate_sequence(
        self, session: Dict, request: ValidationRequest
    ) -> ValidationResult:
        """
        Validate that required tools were called before this tool.

        Runs in two passes:
          1. Single-cloud: config/tool_requirements.yaml (presence-only)
          2. Cross-cloud (Workstream 15): policy.cross_cloud_dependencies
             (target_agent + target_tool + max_age_seconds)

        Args:
            session: Session data with tool_history
            request: Validation request

        Returns:
            ValidationResult with decision (ALLOW/DENY)
        """
        try:
            tool_name = request.tool_name
            tool_history = session.get("tool_history", [])
            called_tools = [item.get("tool_name") for item in tool_history[-10:]]

            logger.debug(
                f"Checking sequence for {tool_name}. History (last 10): {called_tools}"
            )

            # ----- Pass 1: single-cloud requirements (tool_requirements.yaml) -----
            if tool_name in self.requirements:
                required_tools = self.requirements[tool_name].get("requires", [])
                missing_tools = [t for t in required_tools if t not in called_tools]
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

            # ----- Pass 2: cross-cloud dependencies (Workstream 15) -----
            cross_cloud_result = await self._check_cross_cloud_dependencies(
                request, tool_history
            )
            if cross_cloud_result is not None:
                return cross_cloud_result

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

    async def _check_cross_cloud_dependencies(
        self, request: ValidationRequest, tool_history: List[Dict]
    ) -> Optional[ValidationResult]:
        """Workstream 15: enforce policy.cross_cloud_dependencies.

        Returns a DENY ValidationResult if a cross-cloud prerequisite is unmet,
        or None to continue the pipeline. Silently no-ops if no policy_engine
        was injected (degrades gracefully to single-cloud behavior).
        """
        if self.policy_engine is None:
            return None

        try:
            policy = await self.policy_engine.get_agent_policy(request.agent_id)
        except Exception as e:
            # If policy lookup fails here, the policy_engine validator (Step 2)
            # will have already denied. Defensive: no-op.
            logger.debug(f"Cross-cloud dep check: policy lookup failed: {e}")
            return None

        deps = policy.get("cross_cloud_dependencies") or []
        if not deps:
            return None

        # Find dependencies that apply to the requested tool
        applicable = [
            d for d in deps
            if request.tool_name in (d.get("required_before") or [])
        ]
        if not applicable:
            return None

        now_ms = int(time.time() * 1000)

        for dep in applicable:
            target_agent = dep.get("target_agent")
            target_tool = dep.get("target_tool")
            max_age_s = int(dep.get("max_age_seconds", 0))
            if not (target_agent and target_tool and max_age_s > 0):
                # Malformed dep — log and skip (don't fail-secure here; YAML
                # validation should catch malformed deps before they land).
                logger.warning(f"Skipping malformed cross_cloud_dependency: {dep}")
                continue

            cutoff_ms = now_ms - max_age_s * 1000

            # Walk history newest-first looking for a matching entry
            match_found = False
            for entry in reversed(tool_history):
                if entry.get("tool_name") != target_tool:
                    continue
                if entry.get("agent_id") != target_agent:
                    # If agent_id is missing from the entry (legacy data), we
                    # cannot verify cross-cloud provenance — skip this entry.
                    continue
                ts = entry.get("timestamp")
                if ts is None:
                    continue
                try:
                    ts_ms = int(ts)
                except (TypeError, ValueError):
                    continue
                if ts_ms >= cutoff_ms:
                    match_found = True
                    age_s = (now_ms - ts_ms) / 1000.0
                    logger.debug(
                        f"Cross-cloud dep satisfied: {target_agent}.{target_tool} "
                        f"observed {age_s:.1f}s ago (max {max_age_s}s)"
                    )
                    break

            if not match_found:
                logger.warning(
                    f"Cross-cloud dependency NOT met: {request.agent_id} cannot call "
                    f"'{request.tool_name}' without recent {target_agent}.{target_tool} "
                    f"(within {max_age_s}s)"
                )
                return ValidationResult(
                    decision="DENY",
                    reason=(
                        f"cross_cloud_dependency_not_met: "
                        f"{target_agent}.{target_tool} required within {max_age_s}s "
                        f"before '{request.tool_name}'"
                    ),
                    violation_type="CROSS_CLOUD_SEQUENCE_VIOLATION",
                    violated_policy=f"cross_cloud_dependencies:{target_agent}.{target_tool}",
                    penalty=-15,
                    should_deny=True,
                )

        # All applicable cross-cloud dependencies satisfied
        return None
