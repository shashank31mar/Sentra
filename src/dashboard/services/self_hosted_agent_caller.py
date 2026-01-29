"""
Self-Hosted Agent Caller Service

Calls self-hosted agents (customer-query-agent, payment-agent) running on ECS.
These agents use Claude Sonnet 4.5 for natural language response generation.

Reference: Workstream 9, Tasks 1.2 & 1.3
"""

import requests
import logging
import time
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class SelfHostedAgentCaller:
    """Service to call self-hosted agents via their /v1/query endpoints."""

    # Agent service URLs and endpoints (CloudMap Service Discovery)
    AGENT_CONFIG = {
        "customer-query-agent": {
            "base_url": "http://customer-query-agent.sentra.internal:8080",
            "endpoint": "/v1/agents/customer-query/query"
        },
        "payment-agent": {
            "base_url": "http://payment-agent.sentra.internal:8080",
            "endpoint": "/v1/agents/payment/query"
        },
    }

    def __init__(self):
        """Initialize self-hosted agent caller."""
        logger.info("SelfHostedAgentCaller initialized")

    def call_agent(
        self,
        agent_id: str,
        user_message: str,
        session_id: str,
        timeout: int = 10
    ) -> Dict[str, Any]:
        """
        Call self-hosted agent's /v1/query endpoint.

        The agent will:
        1. Process message with Claude Sonnet 4.5
        2. Validate with Security Controller internally
        3. Execute tools if needed
        4. Return natural language response

        Args:
            agent_id: Agent identifier (e.g., "customer-query-agent")
            user_message: User's input message
            session_id: Session ID for tracking
            timeout: Request timeout in seconds

        Returns:
            Dictionary with:
            {
                'response': str,        # Natural language response
                'success': bool,        # Whether call succeeded
                'latency_ms': int,      # Total latency
                'error': str            # Error message (if failed)
            }
        """
        start_time = time.time()

        # Get agent configuration
        agent_config = self.AGENT_CONFIG.get(agent_id)
        if not agent_config:
            logger.error(f"Unknown agent: {agent_id}")
            return {
                'response': f"⚠️ Unknown agent: {agent_id}",
                'success': False,
                'latency_ms': 0,
                'error': f"Agent {agent_id} not found"
            }

        # Build request
        endpoint = f"{agent_config['base_url']}{agent_config['endpoint']}"
        payload = {
            "message": user_message,
            "session_id": session_id
        }

        logger.info(
            f"Calling agent {agent_id}",
            extra={
                "agent_id": agent_id,
                "session_id": session_id,
                "endpoint": endpoint,
                "message_length": len(user_message)
            }
        )

        try:
            # Call agent
            response = requests.post(
                endpoint,
                json=payload,
                timeout=timeout,
                headers={"Content-Type": "application/json"}
            )

            latency_ms = int((time.time() - start_time) * 1000)

            # Check response
            if response.status_code == 200:
                data = response.json()
                agent_response = data.get('response', '')

                logger.info(
                    f"Agent call successful",
                    extra={
                        "agent_id": agent_id,
                        "session_id": session_id,
                        "latency_ms": latency_ms,
                        "response_length": len(agent_response)
                    }
                )

                return {
                    'response': agent_response,
                    'success': True,
                    'latency_ms': latency_ms,
                    'error': None,
                    'data': data.get('data', {})
                }

            else:
                error_msg = f"Agent returned {response.status_code}"
                logger.error(
                    f"Agent call failed",
                    extra={
                        "agent_id": agent_id,
                        "session_id": session_id,
                        "status_code": response.status_code,
                        "error": error_msg
                    }
                )

                return {
                    'response': f"⚠️ Agent error: {error_msg}",
                    'success': False,
                    'latency_ms': latency_ms,
                    'error': error_msg
                }

        except requests.exceptions.Timeout:
            latency_ms = int((time.time() - start_time) * 1000)
            error_msg = f"Agent timeout after {timeout}s"
            logger.error(
                f"Agent call timeout",
                extra={
                    "agent_id": agent_id,
                    "session_id": session_id,
                    "timeout": timeout
                }
            )

            return {
                'response': f"⚠️ Agent timeout - please try again",
                'success': False,
                'latency_ms': latency_ms,
                'error': error_msg
            }

        except requests.exceptions.ConnectionError as e:
            latency_ms = int((time.time() - start_time) * 1000)
            error_msg = f"Cannot connect to agent: {str(e)}"
            logger.error(
                f"Agent connection error",
                extra={
                    "agent_id": agent_id,
                    "session_id": session_id,
                    "error": str(e)
                }
            )

            return {
                'response': f"⚠️ Cannot connect to agent - is it running?",
                'success': False,
                'latency_ms': latency_ms,
                'error': error_msg
            }

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)
            logger.exception(
                f"Agent call failed",
                extra={
                    "agent_id": agent_id,
                    "session_id": session_id,
                    "error": error_msg
                }
            )

            return {
                'response': f"⚠️ Error calling agent: {error_msg}",
                'success': False,
                'latency_ms': latency_ms,
                'error': error_msg
            }


# Singleton instance
self_hosted_agent_caller = SelfHostedAgentCaller()
