"""
Policy Engine - Step 2 of Validation Pipeline

Validates agent authorization and tool permissions.
Checks if agent is allowed to use the requested tool and invoke other agents.

Requirements: LLD 03 Section 3.3, 8.1
Updated: Task 1.7 - Hybrid DynamoDB + S3 storage
"""
import logging
from typing import Dict, Optional

import boto3
import yaml
from botocore.exceptions import ClientError

from app.api.models import ValidationRequest, ValidationResult
from app.combiners import Source
from app.config import settings
from app.validators._signal_stamp import stamps

logger = logging.getLogger(__name__)


class PolicyNotFoundError(Exception):
    """Raised when agent policy doesn't exist"""
    pass


class PolicyEngine:
    """
    Validates agent policies and tool permissions.
    
    Uses hybrid storage approach (Task 1.7):
    - DynamoDB: Policy metadata (sentra-policies-metadata)
    - S3: Full policy YAML content
    
    Checks:
    - Is tool authorized for this agent?
    - If invoking another agent, is that allowed?
    """
    
    def __init__(self):
        self.dynamodb = boto3.resource('dynamodb', region_name=settings.aws_region)
        self.metadata_table = self.dynamodb.Table(settings.dynamodb_policies_metadata_table)
        self.s3_client = boto3.client('s3', region_name=settings.aws_region)
    
    async def get_agent_policy(self, agent_id: str) -> Dict:
        """
        Load policy using hybrid DynamoDB + S3 approach.
        
        Process:
        1. Query sentra-policies-metadata table by agent_id (GSI)
        2. Get s3_bucket and s3_key from metadata
        3. Download full policy YAML from S3
        4. Parse and return policy dict
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            Policy dict with allowed_tools, allowed_agents, policies
            
        Raises:
            PolicyNotFoundError: If no active policy found for agent
        """
        try:
            # Step 1: Query metadata table using agent-index GSI
            response = self.metadata_table.query(
                IndexName='agent-index',
                KeyConditionExpression='agent_id = :agent_id',
                FilterExpression='#status = :status',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={
                    ':agent_id': agent_id,
                    ':status': 'active'
                },
                Limit=1,
                ScanIndexForward=False  # Get latest version first
            )
            
            if not response.get('Items'):
                logger.error(f"No active policy metadata found for agent: {agent_id}")
                raise PolicyNotFoundError(f"Agent {agent_id} has no active policy")
            
            metadata = response['Items'][0]
            logger.debug(f"Loaded policy metadata for agent {agent_id}: {metadata.get('policy_id')}")
            
            # Step 2: Download full policy YAML from S3
            s3_bucket = metadata.get('s3_bucket')
            s3_key = metadata.get('s3_key')
            
            if not s3_bucket or not s3_key:
                raise PolicyNotFoundError(f"Policy metadata missing S3 reference for agent {agent_id}")
            
            policy_obj = self.s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
            policy_content = policy_obj['Body'].read().decode('utf-8')
            
            # Step 3: Parse YAML
            policy_data = yaml.safe_load(policy_content)
            
            logger.debug(f"Loaded policy from S3: {s3_key}")
            return policy_data
            
        except PolicyNotFoundError:
            raise
        except ClientError as e:
            logger.exception(f"AWS error loading policy for {agent_id}")
            raise PolicyNotFoundError(f"Failed to load policy: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error loading policy for {agent_id}")
            raise PolicyNotFoundError(f"Unexpected error: {e}")
    
    @stamps(Source.SENTRA_POLICY)
    async def validate(self, request: ValidationRequest) -> ValidationResult:
        """
        Validate request against agent policy.

        Args:
            request: Validation request

        Returns:
            ValidationResult with decision (ALLOW/DENY). Workstream 15: every
            returned ValidationResult is annotated with the policy's platform
            and cloud_region (when available) so the orchestrator can surface
            them in the response and audit log.
        """
        # Cross-cloud fields surfaced on every result. Resolved from the policy
        # after it's loaded; remain None if the policy can't be loaded.
        platform: Optional[str] = None
        cloud_region: Optional[str] = None

        try:
            # Load agent policy
            try:
                policy = await self.get_agent_policy(request.agent_id)
            except PolicyNotFoundError as e:
                logger.error(f"Policy not found for agent {request.agent_id}")
                # Fail-secure: deny if policy doesn't exist
                return ValidationResult(
                    decision="DENY",
                    reason=f"No policy found for agent {request.agent_id}",
                    violation_type="POLICY_NOT_FOUND",
                    penalty=-15,
                    should_deny=True,
                    platform=platform,
                    cloud_region=cloud_region,
                )

            # Workstream 15: resolve cross-cloud fields from the loaded policy
            platform = policy.get("platform")
            cloud_region = policy.get("cloud_region")

            # Check 1: Is tool authorized?
            allowed_tools = policy.get('allowed_tools', [])
            if request.tool_name not in allowed_tools:
                logger.warning(
                    f"Unauthorized tool: {request.tool_name} not in "
                    f"allowed_tools for {request.agent_id}"
                )
                return ValidationResult(
                    decision="DENY",
                    reason=f"Tool '{request.tool_name}' not authorized for {request.agent_id}",
                    violation_type="UNAUTHORIZED_TOOL",
                    penalty=-15,
                    should_deny=True,
                    platform=platform,
                    cloud_region=cloud_region,
                )

            # Check 2: Tool-specific parameter validation
            # Check refund amount limit for process_refund
            if request.tool_name == "process_refund":
                raw_amount = request.tool_params.get("amount", 0)
                max_refund = policy.get('max_refund_amount', 5000)  # Default $5,000

                # Coerce both sides to numbers. Claude sometimes forwards
                # tool params as strings (e.g., "100000" or "$100,000")
                # because the user prompt embeds the value in natural
                # language. A non-coercible amount is itself a policy
                # violation — DENY rather than ALLOW (fail-secure).
                try:
                    amount = float(
                        str(raw_amount).replace("$", "").replace(",", "").strip()
                    )
                except (TypeError, ValueError):
                    logger.warning(
                        f"Non-numeric refund amount: {raw_amount!r}"
                    )
                    return ValidationResult(
                        decision="DENY",
                        reason=f"Refund amount {raw_amount!r} is not a valid number",
                        violation_type="POLICY_VIOLATION",
                        violated_policy="max_refund_amount",
                        penalty=-10,
                        should_deny=True,
                        platform=platform,
                        cloud_region=cloud_region,
                    )

                try:
                    max_refund_value = float(max_refund)
                except (TypeError, ValueError):
                    # Bad policy data is an operator bug, not a user one.
                    # Fall back to the documented default rather than crash.
                    logger.error(
                        f"max_refund_amount in policy is not numeric: "
                        f"{max_refund!r}; falling back to 5000"
                    )
                    max_refund_value = 5000.0

                if amount > max_refund_value:
                    logger.warning(
                        f"Refund amount ${amount} exceeds limit ${max_refund_value}"
                    )
                    return ValidationResult(
                        decision="DENY",
                        reason=f"Refund amount ${amount} exceeds maximum allowed ${max_refund_value}",
                        violation_type="POLICY_VIOLATION",
                        violated_policy="max_refund_amount",
                        penalty=-10,
                        should_deny=True,
                        platform=platform,
                        cloud_region=cloud_region,
                    )

            # Check 2b: High-fraud identity gate (hardcoded, same pattern as the refund limit).
            # The Azure identity agent carries the real IEEE-CIS fraud data and forwards the
            # subject's risk band in tool_params. A 'high' band means the controller refuses the
            # verification itself — so it is NOT recorded in tool_history, and any downstream
            # cross-cloud op (refund / SIM-swap) that requires a prior verify is then denied by the
            # cross_cloud_dependency check. Real fraud data -> a real Sentra DENY -> blast-radius
            # containment across clouds.
            if request.tool_name == "verify_identity":
                fraud_risk = str(request.tool_params.get("fraud_risk", "")).lower()
                if fraud_risk == "high":
                    fraud_score = request.tool_params.get("fraud_score")
                    logger.warning(
                        f"verify_identity refused: high fraud risk for "
                        f"{request.tool_params.get('subject_id')} (score={fraud_score})"
                    )
                    return ValidationResult(
                        decision="DENY",
                        reason=(
                            "Identity verification refused: subject flagged high fraud risk "
                            f"(IEEE-CIS score={fraud_score})"
                        ),
                        violation_type="POLICY_VIOLATION",
                        violated_policy="high_fraud_identity_block",
                        penalty=-15,
                        should_deny=True,
                        platform=platform,
                        cloud_region=cloud_region,
                    )

            # Check 3: If invoking another agent, is that allowed?
            if request.tool_name == "invoke_agent":
                target_agent = request.tool_params.get("agent_id")
                allowed_agents = policy.get('allowed_agents', [])

                if not target_agent:
                    logger.warning(f"invoke_agent called without target agent_id")
                    return ValidationResult(
                        decision="DENY",
                        reason="invoke_agent requires target agent_id parameter",
                        violation_type="INVALID_AGENT_INVOCATION",
                        penalty=-15,
                        should_deny=True,
                        platform=platform,
                        cloud_region=cloud_region,
                    )

                if target_agent not in allowed_agents:
                    logger.warning(
                        f"Unauthorized agent invocation: {request.agent_id} "
                        f"cannot invoke {target_agent}"
                    )
                    return ValidationResult(
                        decision="DENY",
                        reason=f"Agent '{request.agent_id}' cannot invoke '{target_agent}'",
                        violation_type="UNAUTHORIZED_AGENT_INVOCATION",
                        penalty=-15,
                        should_deny=True,
                        platform=platform,
                        cloud_region=cloud_region,
                    )

            # All checks passed
            logger.debug(
                f"Policy check PASSED: {request.agent_id} authorized for {request.tool_name} "
                f"(platform={platform}, cloud_region={cloud_region})"
            )
            return ValidationResult(
                decision="ALLOW",
                reason="Policy checks passed",
                should_deny=False,
                platform=platform,
                cloud_region=cloud_region,
            )

        except Exception as e:
            logger.exception(f"Policy validation error: {e}")
            # Fail-secure: deny on errors
            return ValidationResult(
                decision="DENY",
                reason="Policy validation failed",
                violation_type="POLICY_ERROR",
                penalty=-15,
                should_deny=True,
                platform=platform,
                cloud_region=cloud_region,
            )
