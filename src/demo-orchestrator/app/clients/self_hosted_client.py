"""
Self-Hosted Agent Client
Sentra MVP - Workstream 13, Task 1.3
"""

import os
import logging
import httpx
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Agent URL mappings
AGENT_URLS = {
    "payment-agent": os.environ.get(
        "PAYMENT_AGENT_URL", 
        "http://payment-agent.sentra.internal:8080"
    ),
    "customer-query-agent": os.environ.get(
        "CUSTOMER_QUERY_AGENT_URL",
        "http://customer-query-agent.sentra.internal:8080"
    )
}


class SelfHostedAgentClient:
    """Client for calling self-hosted ECS agents"""
    
    def __init__(self, timeout: float = 90.0):
        """
        Initialize client with timeout.

        Args:
            timeout: Request timeout in seconds (default 90s for Claude + tool calls)
        """
        self.timeout = timeout
    
    async def send_prompt(
        self,
        agent_name: str,
        prompt: str,
        metadata: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send prompt to self-hosted agent via /v1/query endpoint

        Args:
            agent_name: Name of agent (payment-agent, customer-query-agent)
            prompt: User prompt text
            metadata: Optional metadata (scenario_id, run_id, prompt_id, etc.)
            session_id: Optional session ID for audit log correlation

        Returns:
            Agent response dict with inferred decision
        """
        agent_url = self._get_agent_url(agent_name)

        payload = {
            "message": prompt,
            "context": metadata or {}
        }

        # Add session_id to payload if provided (for audit log correlation)
        if session_id:
            payload["session_id"] = session_id
        
        # Extract scenario info for logging
        scenario_id = metadata.get("scenario_id", "unknown") if metadata else "unknown"
        prompt_id = metadata.get("prompt_id", "unknown") if metadata else "unknown"
        
        logger.info(
            f"Sending prompt to agent",
            extra={
                "agent": agent_name,
                "scenario_id": scenario_id,
                "prompt_id": prompt_id,
                "prompt_preview": prompt[:80] + "..." if len(prompt) > 80 else prompt
            }
        )
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{agent_url}/v1/agents/{agent_name.replace('-agent', '')}/query",
                    json=payload
                )
                response.raise_for_status()
                result = response.json()
                
                # Infer decision from response
                decision = self._infer_decision(result, response.status_code)
                result["decision"] = decision
                
                logger.info(
                    f"Agent response received",
                    extra={
                        "agent": agent_name,
                        "scenario_id": scenario_id,
                        "prompt_id": prompt_id,
                        "status": response.status_code,
                        "decision": decision,
                        "response_preview": result.get("response", "")[:100] if result.get("response") else "N/A"
                    }
                )
                
                return result
                
        except httpx.TimeoutException:
            logger.error(
                f"Timeout calling agent",
                extra={
                    "agent": agent_name,
                    "scenario_id": scenario_id,
                    "prompt_id": prompt_id
                }
            )
            return {
                "decision": "ERROR",
                "reason": f"Agent timeout: {agent_name}",
                "agent_id": agent_name
            }
        except httpx.HTTPStatusError as e:
            # Try to extract error details from response body
            try:
                error_body = e.response.json()
                error_msg = error_body.get("detail", {})
                if isinstance(error_msg, dict):
                    error_text = error_msg.get("error", str(e))
                    error_code = error_msg.get("error_code", "UNKNOWN")
                    matched_rules = error_msg.get("matched_rules", [])
                else:
                    error_text = str(error_msg)
                    error_code = "UNKNOWN"
                    matched_rules = []
            except:
                error_text = str(e)
                error_code = "UNKNOWN"
                matched_rules = []
            
            # Determine decision based on status code and error_code
            # 403 with SECURITY_VALIDATION_FAILED = Security Controller DENY
            # 403 with CHILD_AGENT_DENIED = Child agent denied in multi-agent workflow
            if e.response.status_code == 403:
                if error_code in ["SECURITY_VALIDATION_FAILED", "CHILD_AGENT_DENIED"]:
                    decision = "DENY"
                else:
                    decision = "DENY"  # Any 403 is a denial
            else:
                decision = "ERROR"
            
            logger.info(
                f"Agent request blocked/failed",
                extra={
                    "agent": agent_name,
                    "scenario_id": scenario_id,
                    "prompt_id": prompt_id,
                    "status": e.response.status_code,
                    "decision": decision,
                    "error_code": error_code,
                    "error": error_text,
                    "matched_rules": matched_rules
                }
            )
            
            return {
                "decision": decision,
                "reason": error_text,
                "error_code": error_code,
                "agent_id": agent_name,
                "status_code": e.response.status_code,
                "matched_rules": matched_rules
            }
        except Exception as e:
            logger.error(
                f"Error calling agent",
                extra={
                    "agent": agent_name,
                    "scenario_id": scenario_id,
                    "prompt_id": prompt_id,
                    "error": str(e)
                }
            )
            return {
                "decision": "ERROR",
                "reason": str(e),
                "agent_id": agent_name
            }
    
    def _infer_decision(self, result: Dict[str, Any], status_code: int) -> str:
        """
        Infer decision from agent response
        
        Self-hosted agents return:
        - 200 with response = ALLOW (request processed)
        - 403 = DENY (Security Controller blocked)
        - Other errors = ERROR
        
        Also check response text for denial patterns
        """
        if status_code != 200:
            return "ERROR"
        
        response_text = result.get("response", "").lower()
        
        # Check for denial patterns in the response text
        denial_patterns = [
            "i apologize",
            "i'm sorry",
            "i cannot",
            "i can't",
            "cannot help",
            "unable to",
            "security policy",
            "blocked",
            "denied",
            "not allowed",
            "cannot process",
            "unable to complete",
            "request was denied",
            "policy violation",
            "against policy",
            "do not have access",
            "should not",
            "will not"
        ]
        
        for pattern in denial_patterns:
            if pattern in response_text:
                return "DENY"
        
        # Check if there's an error field
        if result.get("error"):
            return "ERROR"
        
        # Check data for security-related fields
        data = result.get("data", {})
        if data.get("blocked") or data.get("denied"):
            return "DENY"
        
        # Default: request was allowed and processed
        return "ALLOW"
    
    def _get_agent_url(self, agent_name: str) -> str:
        """Get URL for agent by name"""
        if agent_name in AGENT_URLS:
            return AGENT_URLS[agent_name]
        
        # Try environment variable pattern
        env_key = f"{agent_name.upper().replace('-', '_')}_URL"
        url = os.environ.get(env_key)
        
        if url:
            return url
        
        raise ValueError(f"Unknown agent: {agent_name}. Set {env_key} environment variable.")
