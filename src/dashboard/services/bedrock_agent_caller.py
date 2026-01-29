"""
Bedrock Agent Caller Service

Invokes AWS Bedrock Agents with Sentra validation.

ARCHITECTURE NOTE:
- Sentra validation happens in the Action Group Lambda (NOT in guardrails)
- Lambda calls Sentra /validate API before executing tools
- Guardrails handle AWS built-in filters (PII, content filtering)
- This service invokes the agent and extracts validation results from traces

Reference:
- Workstream 9, Task 3.3
- LLD 09 Section 2.5.4
- docs/bedrock-agent-architecture-clarification.md

Usage:
    from services.bedrock_agent_caller import BedrockAgentCaller

    caller = BedrockAgentCaller()
    result = caller.invoke_agent(
        agent_id="GZDBCCWFVT",
        agent_alias_id="TSTALIASID",
        session_id="test-session-123",
        user_message="Show customers from California"
    )
"""

import boto3
import json
import logging
import time
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class BedrockAgentCaller:
    """Service to invoke AWS Bedrock Agents and parse guardrail validation traces."""

    def __init__(self, region_name: str = 'us-east-1'):
        """
        Initialize Bedrock Agent Runtime client.

        Args:
            region_name: AWS region (default: us-east-1)
        """
        self.region_name = region_name
        self.bedrock_agent_runtime = boto3.client(
            service_name='bedrock-agent-runtime',
            region_name=region_name
        )
        logger.info(f"BedrockAgentCaller initialized for region: {region_name}")

    def invoke_agent(
        self,
        agent_id: str,
        agent_alias_id: str,
        session_id: str,
        user_message: str,
        enable_trace: bool = True
    ) -> Dict[str, Any]:
        """
        Invoke AWS Bedrock Agent with Sentra validation.

        VALIDATION FLOW:
        1. User message → Bedrock Agent
        2. Agent decides tool to call
        3. Action Group Lambda invoked
        4. Lambda calls Sentra /validate API (with Secrets Manager API key)
        5. If ALLOW: Lambda executes tool
        6. If DENY: Lambda returns 403 error
        7. Agent formats response

        Args:
            agent_id: Bedrock agent ID (e.g., "GZDBCCWFVT")
            agent_alias_id: Agent alias (e.g., "TSTALIASID", "PROD")
            session_id: Session ID for conversation continuity
            user_message: User's input message
            enable_trace: Enable guardrail trace extraction (default: True)

        Returns:
            Dictionary with:
            {
                'response': str,              # Agent's response text
                'decision': str,              # 'ALLOW' or 'DENY'
                'validation_result': dict,    # Sentra validation details
                'latency_ms': int,            # Total latency
                'trace': dict,                # Full trace (if enabled)
                'error': str                  # Error message (if failed)
            }
        """
        start_time = time.time()

        logger.info(
            f"Invoking Bedrock Agent",
            extra={
                "agent_id": agent_id,
                "agent_alias_id": agent_alias_id,
                "session_id": session_id,
                "user_message": user_message[:100]  # Log first 100 chars
            }
        )

        try:
            # Call Bedrock Agent Runtime API
            # Note: Using create-invocation (new API as of 2025)
            response = self.bedrock_agent_runtime.invoke_agent(
                agentId=agent_id,
                agentAliasId=agent_alias_id,
                sessionId=session_id,
                inputText=user_message,
                enableTrace=enable_trace
            )

            # Parse streaming response
            event_stream = response.get('completion', [])
            full_response = ""
            validation_result = None
            trace_data = {}
            guardrail_trace = None

            for event in event_stream:
                # Extract agent response chunks
                if 'chunk' in event:
                    chunk = event['chunk']
                    if 'bytes' in chunk:
                        chunk_text = chunk['bytes'].decode('utf-8')
                        full_response += chunk_text

                # Extract guardrail validation trace
                if 'trace' in event and enable_trace:
                    trace = event['trace'].get('trace', {})

                    # Store full trace
                    if 'orchestrationTrace' in trace:
                        trace_data['orchestration'] = trace['orchestrationTrace']

                    # Extract guardrail trace
                    if 'guardrailTrace' in trace:
                        guardrail_trace = trace['guardrailTrace']
                        validation_result = self._parse_guardrail_trace(guardrail_trace)

                        # Check if blocked by guardrail
                        if validation_result and validation_result.get('decision') == 'DENY':
                            logger.warning(
                                "Request blocked by Sentra guardrail",
                                extra={
                                    "session_id": session_id,
                                    "reason": validation_result.get('reason'),
                                    "threat_type": validation_result.get('threat_type')
                                }
                            )

                            latency_ms = int((time.time() - start_time) * 1000)

                            return {
                                'response': validation_result.get('reason', '⚠️ Request blocked by security policy'),
                                'decision': 'DENY',
                                'validation_result': validation_result,
                                'latency_ms': latency_ms,
                                'trace': trace_data,
                                'error': None
                            }

            latency_ms = int((time.time() - start_time) * 1000)

            logger.info(
                f"Bedrock Agent invocation successful",
                extra={
                    "agent_id": agent_id,
                    "session_id": session_id,
                    "latency_ms": latency_ms,
                    "response_length": len(full_response),
                    "validation_decision": validation_result.get('decision') if validation_result else 'N/A'
                }
            )

            return {
                'response': full_response,
                'decision': 'ALLOW',
                'validation_result': validation_result,
                'latency_ms': latency_ms,
                'trace': trace_data,
                'error': None
            }

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            error_message = str(e)

            logger.error(
                f"Bedrock agent invocation failed: {error_message}",
                extra={
                    "agent_id": agent_id,
                    "session_id": session_id,
                    "latency_ms": latency_ms
                }
            )

            return {
                'response': f"⚠️ Error invoking agent: {error_message}",
                'decision': 'ERROR',
                'validation_result': None,
                'latency_ms': latency_ms,
                'trace': {},
                'error': error_message
            }

    def _parse_guardrail_trace(self, guardrail_trace: Dict) -> Optional[Dict[str, Any]]:
        """
        Parse guardrail trace to extract Sentra validation result.

        Bedrock guardrail trace format:
        {
            "action": "INTERVENED" | "NONE",
            "inputAssessments": [...],
            "outputAssessments": [...],
            "customApiTrace": {
                "request": {...},
                "response": {...}
            }
        }

        Args:
            guardrail_trace: Guardrail trace from Bedrock event

        Returns:
            Parsed validation result or None
        """
        if not guardrail_trace:
            return None

        try:
            # Check if guardrail intervened
            action = guardrail_trace.get('action')

            # Extract custom API response (Sentra validation)
            if 'customApiTrace' in guardrail_trace:
                custom_api_trace = guardrail_trace['customApiTrace']

                if 'response' in custom_api_trace:
                    # Parse Sentra API response
                    sentra_response = custom_api_trace['response']

                    # If response is string, try to parse as JSON
                    if isinstance(sentra_response, str):
                        try:
                            sentra_response = json.loads(sentra_response)
                        except json.JSONDecodeError:
                            logger.warning(f"Could not parse Sentra response as JSON: {sentra_response}")
                            return None

                    return {
                        'decision': sentra_response.get('decision', 'UNKNOWN'),
                        'reason': sentra_response.get('reason', 'No reason provided'),
                        'request_id': sentra_response.get('request_id'),
                        'trust_score': sentra_response.get('trust_score'),
                        'threat_type': sentra_response.get('threat_type'),
                        'violation_type': sentra_response.get('violation_type'),
                        'violated_policy': sentra_response.get('violated_policy'),
                        'guardrail_action': action,
                        'timestamp': datetime.utcnow().isoformat() + 'Z'
                    }

            # Fallback: Check input/output assessments
            input_assessments = guardrail_trace.get('inputAssessments', [])
            if input_assessments:
                for assessment in input_assessments:
                    if assessment.get('action') == 'BLOCKED':
                        return {
                            'decision': 'DENY',
                            'reason': 'Blocked by Bedrock guardrail content filter',
                            'guardrail_action': action,
                            'timestamp': datetime.utcnow().isoformat() + 'Z'
                        }

            # No intervention
            return {
                'decision': 'ALLOW',
                'reason': 'No guardrail intervention',
                'guardrail_action': action,
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }

        except Exception as e:
            logger.error(f"Error parsing guardrail trace: {e}")
            return None

    def list_agent_sessions(self, agent_id: str, agent_alias_id: str) -> list:
        """
        List active sessions for an agent.

        Args:
            agent_id: Bedrock agent ID
            agent_alias_id: Agent alias ID

        Returns:
            List of session summaries
        """
        try:
            response = self.bedrock_agent_runtime.list_sessions(
                agentId=agent_id,
                agentAliasId=agent_alias_id
            )
            return response.get('sessionSummaries', [])
        except Exception as e:
            logger.error(f"Failed to list agent sessions: {e}")
            return []

    def delete_agent_session(self, agent_id: str, agent_alias_id: str, session_id: str) -> bool:
        """
        Delete an agent session.

        Args:
            agent_id: Bedrock agent ID
            agent_alias_id: Agent alias ID
            session_id: Session ID to delete

        Returns:
            True if successful, False otherwise
        """
        try:
            self.bedrock_agent_runtime.delete_session(
                agentId=agent_id,
                agentAliasId=agent_alias_id,
                sessionId=session_id
            )
            logger.info(f"Deleted session: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
            return False


# Example usage
if __name__ == '__main__':
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Example: Invoke Bedrock Agent
    caller = BedrockAgentCaller()

    result = caller.invoke_agent(
        agent_id="GZDBCCWFVT",
        agent_alias_id="TSTALIASID",
        session_id=f"test-{int(time.time())}",
        user_message="Show me customers from California"
    )

    print("\n" + "="*70)
    print("Bedrock Agent Response")
    print("="*70)
    print(f"Decision: {result['decision']}")
    print(f"Response: {result['response']}")
    print(f"Latency: {result['latency_ms']}ms")

    if result['validation_result']:
        print("\nValidation Result:")
        print(json.dumps(result['validation_result'], indent=2))

    if result['error']:
        print(f"\nError: {result['error']}")
    print("="*70)
