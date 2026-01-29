"""
Real Chat Service - Connects to Security Controller for chat validation.

Milestone 7: Replaces mock_chat_service.py with real API calls.
Milestone 9.2: Added LLM-generated DENY responses (Task 2.1)
"""
from typing import Dict, List
from datetime import datetime
import logging
import time
import sys
import os

from .security_controller_client import SecurityControllerClient
from .self_hosted_agent_caller import self_hosted_agent_caller

# Import LLM response generator from common module
# Docker structure: /app/common/llm_response_generator.py
# Local dev structure: src/dashboard/services/../common/ -> src/common/
try:
    # Try Docker path (common/ at /app root level)
    from common.llm_response_generator import LLMResponseGenerator
except ImportError:
    try:
        # Try local dev path (one level up from services/, then to common/)
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../common'))
        from llm_response_generator import LLMResponseGenerator
    except ImportError:
        # Final fallback: go up to src/ then to common/
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../common'))
        from llm_response_generator import LLMResponseGenerator

logger = logging.getLogger(__name__)


class RealChatService:
    """Real chat service that connects to Security Controller API."""

    def __init__(self):
        """Initialize real chat service."""
        self.client = SecurityControllerClient()
        self.sessions = {}  # session_id -> session data (local cache)
        self.messages = {}  # session_id -> list of messages (local cache)
        
        # Initialize LLM response generator for DENY messages (Task 2.1)
        try:
            self.llm_generator = LLMResponseGenerator()
            logger.info("LLM Response Generator initialized for DENY messages")
        except Exception as e:
            logger.warning(f"Failed to initialize LLM generator: {e}. Will use fallback responses.")
            self.llm_generator = None

    def create_session(self, agent_id: str, agent_name: str) -> Dict:
        """
        Create a new chat session.

        Args:
            agent_id: Agent ID (e.g., 'customer-query-agent')
            agent_name: Agent display name

        Returns:
            Session dictionary
        """
        session_id = f"sess-{agent_id}-{int(time.time())}"
        session = {
            'session_id': session_id,
            'agent_id': agent_id,
            'agent_name': agent_name,
            'trust_score': 100.0,
            'initial_trust_score': 100.0,
            'message_count': 0,
            'allowed_count': 0,
            'blocked_count': 0,
            'created_at': datetime.now().isoformat() + 'Z',
        }
        self.sessions[session_id] = session
        self.messages[session_id] = []

        logger.info(f"Created session {session_id} for agent {agent_id}")
        return session

    def send_message(self, session_id: str, user_message: str) -> Dict:
        """
        Send a message through Security Controller for validation.

        Args:
            session_id: Session ID
            user_message: User's message

        Returns:
            Agent response dictionary
        """
        if session_id not in self.sessions:
            raise ValueError(f"Session {session_id} not found")

        session = self.sessions[session_id]
        messages = self.messages[session_id]

        # Add user message
        user_msg = {
            'role': 'user',
            'content': user_message,
            'timestamp': datetime.now().isoformat() + 'Z',
        }
        messages.append(user_msg)

        # Capture old trust score BEFORE validation
        old_trust_score = session.get('trust_score', 100.0)

        # Infer tool and parameters from message
        tool_name, tool_params = self._infer_tool_and_params(user_message)

        # Generate unique request ID
        request_id = f"req-{session_id}-{int(time.time() * 1000)}"

        # Determine operation type based on tool name
        operation_type = "WRITE" if any(op in tool_name.lower() for op in ['process', 'create', 'update', 'delete', 'refund', 'payment']) else "READ"

        # Send to Security Controller for validation
        start_time = time.time()
        try:
            validation_result = self.client.validate_request(
                request_id=request_id,
                agent_id=session['agent_id'],
                session_id=session_id,
                user_input=user_message,
                tool_name=tool_name,
                tool_params=tool_params,
                operation_type=operation_type,
            )
            latency_ms = int((time.time() - start_time) * 1000)

            decision = validation_result.get('decision', 'DENY')
            threat_type = validation_result.get('threat_type')
            violation_type = validation_result.get('violation_type')
            reason = validation_result.get('reason', 'Unknown')
            result = validation_result.get('result', {})

            # Calculate trust delta based on decision
            # For DENY: Get actual penalty from validation result or use default
            # For ALLOW: Trust score may increase slightly for good behavior
            trust_delta = 0.0

            if decision == 'DENY':
                # Blocked response
                # Trust score is updated by Security Controller, we'll use the returned value
                new_trust_score = validation_result.get('trust_score', old_trust_score)
                session['trust_score'] = new_trust_score
                trust_delta = new_trust_score - old_trust_score

                # Determine if this is a policy violation or threat detection
                denial_category = "threat" if threat_type else "policy"
                denial_type = threat_type or violation_type or "UNKNOWN"

                # Task 2.1: Generate LLM-formatted DENY response
                denial_content = self._generate_denial_response(
                    user_message=user_message,
                    validation_result=validation_result
                )

                agent_msg = {
                    'role': 'agent',
                    'content': denial_content,  # Now uses LLM-generated response
                    'timestamp': datetime.now().isoformat() + 'Z',
                    'decision': 'DENY',
                    'denial_category': denial_category,  # "threat" or "policy"
                    'denial_type': denial_type,  # Specific type (PROMPT_INJECTION, POLICY_VIOLATION, etc.)
                    'tool_name': tool_name,
                    'latency_ms': latency_ms,
                    'trust_delta': trust_delta,
                }
                session['blocked_count'] += 1
            else:
                # Allowed response - Call self-hosted agent (Tasks 1.2 & 1.3)
                # Agent will execute with Claude Sonnet 4.5 and return natural language response
                # Increased timeout to 120s for LLM processing (Claude Opus 4 can be slow)
                agent_result = self_hosted_agent_caller.call_agent(
                    agent_id=session['agent_id'],
                    user_message=user_message,
                    session_id=session_id,
                    timeout=120  # 2 minutes for LLM + tool execution
                )
                
                # Use agent response if successful, otherwise fallback
                if agent_result['success']:
                    response_content = agent_result['response']
                    logger.info(
                        "Using agent response (success)",
                        extra={
                            "agent_id": session['agent_id'],
                            "session_id": session_id,
                            "agent_latency_ms": agent_result['latency_ms'],
                            "response_preview": response_content[:200]  # Log first 200 chars
                        }
                    )
                else:
                    # Fallback if agent call fails
                    response_content = self._generate_fallback_response(user_message, tool_name)
                    logger.warning(
                        "Agent call failed - USING FALLBACK RESPONSE",
                        extra={
                            "agent_id": session['agent_id'],
                            "session_id": session_id,
                            "error": agent_result['error'],
                            "fallback_response": response_content[:200]  # Log fallback response
                        }
                    )

                # For ALLOW, trust score typically stays same or increases slightly
                # Trust score is updated by Security Controller, we'll use the returned value
                new_trust_score = validation_result.get('trust_score', old_trust_score)
                session['trust_score'] = new_trust_score
                trust_delta = new_trust_score - old_trust_score

                agent_msg = {
                    'role': 'agent',
                    'content': response_content,
                    'timestamp': datetime.now().isoformat() + 'Z',
                    'decision': 'ALLOW',
                    'tool_name': tool_name,
                    'latency_ms': latency_ms,
                    'trust_delta': trust_delta,
                }
                session['allowed_count'] += 1

            messages.append(agent_msg)
            session['message_count'] = len([m for m in messages if m['role'] == 'user'])

            return agent_msg

        except Exception as e:
            logger.error(f"Error sending message to Security Controller: {e}")

            # Return error response
            agent_msg = {
                'role': 'agent',
                'content': f'⚠️ Error communicating with Security Controller: {str(e)}',
                'timestamp': datetime.now().isoformat() + 'Z',
                'decision': 'DENY',
                'threat_type': 'SYSTEM_ERROR',
                'tool_name': tool_name,
                'latency_ms': int((time.time() - start_time) * 1000),
                'trust_delta': 0,
            }
            messages.append(agent_msg)
            return agent_msg

    def get_messages(self, session_id: str) -> List[Dict]:
        """
        Get all messages for a session.

        Args:
            session_id: Session ID

        Returns:
            List of messages
        """
        return self.messages.get(session_id, [])

    def get_session(self, session_id: str) -> Dict:
        """
        Get session data.

        Args:
            session_id: Session ID

        Returns:
            Session dictionary
        """
        return self.sessions.get(session_id)


    def _infer_tool_and_params(self, message: str) -> tuple:
        """
        Infer which tool would be used based on message content.

        Fixed to match actual agent tool schemas (see audit: /tmp/tool_audit_comprehensive.md)

        Args:
            message: User message

        Returns:
            Tuple of (tool_name, tool_params)
        """
        import re
        message_lower = message.lower()

        # ===== FIX 5: get_customer_by_id (specific customer lookup) =====
        # Pattern: "get customer cust-123" or "customer id cust-123" or "find customer by id cust-123"
        if 'customer' in message_lower and any(id_word in message_lower for id_word in ['by id', 'customer id', 'cust-', 'customer-']):
            # Extract customer_id (formats: "cust-123", "CUST-ABC", "customer-id-456")
            cust_match = re.search(r'(?:customer[_\s-]?id[:\s]+|cust-|customer-)([a-zA-Z0-9-]+)', message_lower)
            if cust_match:
                return ('get_customer_by_id', {'customer_id': cust_match.group(1)})
            # Fallback if no ID extracted
            return ('get_customer_by_id', {'customer_id': ''})

        # ===== FIX 4: reverse_refund (check before other refund patterns) =====
        # Pattern: "reverse refund txn-123" or "reverse refund for transaction txn-abc"
        elif 'reverse' in message_lower and 'refund' in message_lower:
            params = {}
            # Extract transaction_id (formats: "txn-123", "transaction-abc", "TXN-ABC-456")
            txn_match = re.search(r'(?:transaction|txn)[_\s#-]?([a-zA-Z0-9-]+)', message_lower)
            if txn_match:
                params['transaction_id'] = txn_match.group(1)
            # Extract reason
            reason_match = re.search(r'(?:reason|because|due to)[:\s]+(.+?)(?:\.|$)', message_lower)
            if reason_match:
                params['reason'] = reason_match.group(1).strip()
            else:
                params['reason'] = 'Manual reversal requested'  # Default reason
            return ('reverse_refund', params)

        # ===== Refund status query (check before process_refund) =====
        # Pattern: "refund status for order ORD-123" or "check refund for order-abc"
        elif 'refund' in message_lower and any(word in message_lower for word in ['status', 'check', 'query', 'show']):
            # Extract order_id
            order_match = re.search(r'order[_\s#-]?([a-zA-Z0-9-]+)', message_lower)
            if order_match:
                return ('query_refund_status', {'order_id': order_match.group(1)})
            return ('query_refund_status', {'order_id': ''})

        # ===== FIX 3: process_refund (check before order patterns) =====
        # Pattern: "process refund $2,000 for order ORD-123" or "refund $500 to order-abc because defective"
        elif 'refund' in message_lower:
            params = {}

            # Extract amount (REQUIRED)
            amount_match = re.search(r'\$?(\d+(?:,\d{3})*(?:\.\d{2})?)', message)
            if amount_match:
                amount_str = amount_match.group(1).replace(',', '')
                params['amount'] = float(amount_str)

            # FIX: Extract order_id (REQUIRED) - multiple formats
            order_match = re.search(r'(?:order|for order)[_\s#-]?([a-zA-Z0-9-]+)', message_lower)
            if order_match:
                params['order_id'] = order_match.group(1)

            # FIX: Extract reason (REQUIRED)
            reason_match = re.search(r'(?:reason|because|due to)[:\s]+(.+?)(?:\.|$)', message_lower)
            if reason_match:
                params['reason'] = reason_match.group(1).strip()
            else:
                # Infer reason from keywords
                if 'defective' in message_lower or 'broken' in message_lower:
                    params['reason'] = 'Defective product'
                elif 'wrong' in message_lower or 'incorrect' in message_lower:
                    params['reason'] = 'Wrong item received'
                elif 'late' in message_lower or 'delay' in message_lower:
                    params['reason'] = 'Late delivery'
                else:
                    params['reason'] = 'Customer request'  # Default

            return ('process_refund', params)

        # ===== FIX 1: query_customers (wrap in filters object) =====
        # Pattern: "show customers from CA" or "find customers in Texas" or "customers named John"
        elif 'customer' in message_lower or 'user' in message_lower:
            filters = {}

            # FIX 7: Support all US states (2-letter codes)
            state_match = re.search(r'\b([A-Z]{2})\b', message)
            if state_match:
                filters['state'] = state_match.group(1)
            # Also support full state names (common ones)
            elif 'california' in message_lower:
                filters['state'] = 'CA'
            elif 'texas' in message_lower:
                filters['state'] = 'TX'
            elif 'new york' in message_lower:
                filters['state'] = 'NY'
            elif 'florida' in message_lower:
                filters['state'] = 'FL'

            # Extract name filter
            if 'named' in message_lower or 'name' in message_lower:
                name_match = re.search(r'(?:named|name[d]?\s+)([A-Za-z\s]+?)(?:\s+(?:from|in|with)|$)', message_lower)
                if name_match:
                    filters['name_contains'] = name_match.group(1).strip()

            # Extract email filter
            if 'email' in message_lower:
                email_match = re.search(r'email\s+(?:contains\s+)?([^\s]+)', message_lower)
                if email_match:
                    filters['email_contains'] = email_match.group(1)

            # Extract limit
            limit_match = re.search(r'(\d+)\s+customer', message_lower)
            if limit_match:
                filters['limit'] = int(limit_match.group(1))

            # CRITICAL FIX: Wrap in filters object
            return ('query_customers', {'filters': filters})

        # ===== List orders (payment agent tool) =====
        # Pattern: "show me 10 orders" or "list recent orders" or "show completed orders"
        elif 'order' in message_lower and any(verb in message_lower for verb in ['list', 'show', 'recent', 'what', 'see', 'get', 'find']) and not any(specific in message_lower for specific in ['order #', 'order id', 'order-']):
            params = {}
            # Extract limit if present (match patterns like "10 orders", "show 5 orders", "5 pending orders")
            limit_match = re.search(r'(\d+)\s+(?:\w+\s+)?order', message_lower)
            if limit_match:
                params['limit'] = int(limit_match.group(1))
            # Extract status filter
            if 'completed' in message_lower:
                params['status'] = 'completed'
            elif 'pending' in message_lower:
                params['status'] = 'pending'
            elif 'refunded' in message_lower:
                params['status'] = 'refunded'
            elif 'shipped' in message_lower:
                params['status'] = 'shipped'
            elif 'delivered' in message_lower:
                params['status'] = 'delivered'
            return ('list_orders', params)

        # ===== FIX 2: query_orders (wrap in filters object) =====
        # Pattern: "show completed orders" or "orders for customer cust-123"
        elif 'order' in message_lower:
            filters = {}

            # FIX 8: Extract order_id (multiple formats)
            # Support: "order #123", "order ORD-123", "order-abc", "order ord-123"
            order_id_match = re.search(r'order[_\s#-]+([a-zA-Z0-9-]+)', message_lower)
            if order_id_match:
                # This is a specific order lookup, not a query
                # Use query_refund_status if asking about refund
                if 'refund' in message_lower and 'status' in message_lower:
                    return ('query_refund_status', {'order_id': order_id_match.group(1)})
                # Otherwise fall through to query_orders with filter
                filters['customer_id'] = order_id_match.group(1)  # Treat as potential customer filter

            # Extract customer_id filter
            cust_match = re.search(r'(?:customer|cust)[_\s-]?([a-zA-Z0-9-]+)', message_lower)
            if cust_match:
                filters['customer_id'] = cust_match.group(1)

            # Extract status filter
            for status in ['completed', 'pending', 'cancelled', 'shipped']:
                if status in message_lower:
                    filters['status'] = status
                    break

            # Extract amount range
            min_amount_match = re.search(r'(?:min|minimum|above|over|greater than)\s+\$?(\d+(?:,\d{3})*(?:\.\d{2})?)', message_lower)
            if min_amount_match:
                filters['min_amount'] = float(min_amount_match.group(1).replace(',', ''))

            max_amount_match = re.search(r'(?:max|maximum|below|under|less than)\s+\$?(\d+(?:,\d{3})*(?:\.\d{2})?)', message_lower)
            if max_amount_match:
                filters['max_amount'] = float(max_amount_match.group(1).replace(',', ''))

            # Extract limit
            limit_match = re.search(r'(\d+)\s+order', message_lower)
            if limit_match:
                filters['limit'] = int(limit_match.group(1))

            # CRITICAL FIX: Wrap in filters object
            return ('query_orders', {'filters': filters})

        # ===== Payment requests (kept for compatibility) =====
        elif 'payment' in message_lower:
            params = {}
            amount_match = re.search(r'\$?(\d+(?:,\d{3})*(?:\.\d{2})?)', message)
            if amount_match:
                amount_str = amount_match.group(1).replace(',', '')
                params['amount'] = float(amount_str)
            return ('process_payment', params)

        # ===== FIX 6: Generic fallback (remove 'query' param) =====
        # Default to query_customers with empty filters
        else:
            return ('query_customers', {'filters': {}})

    def _generate_denial_response(
        self,
        user_message: str,
        validation_result: Dict
    ) -> str:
        """
        Generate user-friendly DENY response using LLM.
        
        Task 2.1: LLM-Generated DENY Responses
        Reference: LLD 09 Section 5.4
        
        Args:
            user_message: Original user request
            validation_result: Security Controller validation result
            
        Returns:
            Natural language denial message
        """
        # Try LLM generation first
        if self.llm_generator:
            try:
                nlp_denial = self.llm_generator.generate_denial_response(
                    user_query=user_message,
                    validation_result=validation_result,
                    timeout=5
                )
                logger.info("Generated LLM-formatted DENY response")
                return nlp_denial
            except Exception as e:
                logger.warning(f"LLM denial formatting failed: {e}, using fallback")
        
        # Fallback to structured response
        reason = validation_result.get('reason', 'Security policy violation')
        return f"⚠️ Request blocked!\nReason: {reason}"

    def _generate_fallback_response(self, message: str, tool_name: str) -> str:
        """
        Generate fallback response if Security Controller doesn't return result.

        Args:
            message: User message
            tool_name: Tool being used

        Returns:
            Response text
        """
        message_lower = message.lower()

        # Customer queries
        if 'customer' in message_lower:
            if 'california' in message_lower or 'ca' in message_lower:
                return "Here are the customers from CA:\n• John Doe (john@example.com)\n• Jane Smith (jane@example.com)"
            else:
                return "Found 47 customers matching your query."

        # Order queries
        elif 'order' in message_lower:
            if '#' in message:
                order_num = message.split('#')[1].split()[0]
                return f"Order #{order_num}: $50.00, Completed"
            else:
                return "Found 15 orders in the last 30 days."

        # Refund requests (normal amounts)
        elif 'refund' in message_lower:
            return "Refund processed successfully. Reference: REF-12345"

        # Payment requests
        elif 'payment' in message_lower:
            return "Payment processed: $25.00. Transaction ID: TXN-67890"

        # Generic response
        else:
            return "Request processed successfully."


# Global instance for use in dashboard
real_chat_service = RealChatService()
