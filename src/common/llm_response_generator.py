"""
LLM Response Generator - AWS Bedrock wrapper for NLP formatting
Sentra MVP - Workstream 9 - Milestone 1

This module provides a reusable Bedrock wrapper for generating natural language
responses from structured data. Supports both ALLOW and DENY scenarios.

Reference: LLD 09 Section 5.1, 5.2, 5.4
"""

import os
import json
import logging
import time
from typing import Dict, List, Any, Optional, Union
from enum import Enum

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class ResponseTemplate(str, Enum):
    """Response template types"""
    CUSTOMER_LIST = "customer_list"
    ORDER_LIST = "order_list"
    CUSTOMER_DETAILS = "customer_details"
    ORDER_DETAILS = "order_details"
    REFUND_CONFIRMATION = "refund_confirmation"
    DENIAL = "denial"
    GENERIC = "generic"


class LLMResponseGenerator:
    """
    Generates natural language responses using AWS Bedrock Claude Sonnet 4.5.

    Features:
    - Template-based prompt engineering
    - Graceful fallback to structured responses
    - Cost optimization with token limits
    - Production-grade error handling
    """

    def __init__(
        self,
        model_id: Optional[str] = None,
        fallback_model_id: Optional[str] = None,
        region_name: Optional[str] = None
    ):
        """
        Initialize LLM Response Generator.

        Args:
            model_id: Bedrock model ID (defaults to Claude Sonnet 4.5)
            fallback_model_id: Fallback model for cost optimization
            region_name: AWS region (defaults to us-east-1)
        """
        self.region_name = region_name or os.environ.get('AWS_REGION', 'us-east-1')

        # Initialize Bedrock client
        try:
            self.bedrock_runtime = boto3.client(
                service_name='bedrock-runtime',
                region_name=self.region_name
            )
        except Exception as e:
            logger.error(f"Failed to initialize Bedrock client: {e}")
            raise

        # Use Claude Sonnet 3.5 v2 (stable, widely available)
        self.model_id = model_id or os.environ.get(
            'BEDROCK_MODEL_ID',
            'us.anthropic.claude-3-5-sonnet-20241022-v2:0'
        )

        # Fallback for cost optimization (Haiku 3.5)
        self.fallback_model_id = fallback_model_id or os.environ.get(
            'BEDROCK_FALLBACK_MODEL_ID',
            'us.anthropic.claude-3-5-haiku-20241022-v1:0'
        )

        logger.info(
            "LLM Response Generator initialized",
            extra={
                "model_id": self.model_id,
                "fallback_model_id": self.fallback_model_id,
                "region": self.region_name
            }
        )

    def generate_response(
        self,
        user_query: str,
        data: Union[List[Dict], Dict, str],
        template_type: Union[ResponseTemplate, str] = ResponseTemplate.GENERIC,
        max_tokens: int = 500,
        temperature: float = 0.7,
        timeout: int = 10
    ) -> str:
        """
        Generate natural language response from structured data.

        Args:
            user_query: Original user question
            data: Structured data from database or validation result
            template_type: Response template type
            max_tokens: Maximum tokens in response (lower = faster + cheaper)
            temperature: Creativity level (0.0-1.0). Lower = more deterministic
            timeout: Request timeout in seconds

        Returns:
            Natural language response string

        Raises:
            Exception: If both primary and fallback generation fail
        """
        start_time = time.time()

        # Convert template_type to enum if string
        if isinstance(template_type, str):
            try:
                template_type = ResponseTemplate(template_type)
            except ValueError:
                logger.warning(f"Invalid template type: {template_type}, using GENERIC")
                template_type = ResponseTemplate.GENERIC

        # Build prompt based on template type
        prompt = self._build_prompt(user_query, data, template_type)

        logger.info(
            "Generating LLM response",
            extra={
                "template_type": template_type.value,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "data_size": len(json.dumps(data)) if not isinstance(data, str) else len(data)
            }
        )

        try:
            # Try primary model
            response_text = self._invoke_bedrock(
                prompt=prompt,
                model_id=self.model_id,
                max_tokens=max_tokens,
                temperature=temperature
            )

            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.info(
                "LLM response generated successfully",
                extra={
                    "model": self.model_id,
                    "elapsed_ms": elapsed_ms,
                    "response_length": len(response_text)
                }
            )

            return response_text

        except Exception as e:
            logger.warning(f"Primary model failed: {e}, trying fallback...")

            try:
                # Try fallback model
                response_text = self._invoke_bedrock(
                    prompt=prompt,
                    model_id=self.fallback_model_id,
                    max_tokens=max_tokens,
                    temperature=temperature
                )

                elapsed_ms = int((time.time() - start_time) * 1000)
                logger.info(
                    "LLM response generated with fallback model",
                    extra={
                        "model": self.fallback_model_id,
                        "elapsed_ms": elapsed_ms
                    }
                )

                return response_text

            except Exception as fallback_error:
                logger.error(f"Fallback model also failed: {fallback_error}")

                # Final fallback: structured response
                return self._fallback_response(data, template_type)

    def generate_denial_response(
        self,
        user_query: str,
        validation_result: Dict[str, Any],
        timeout: int = 5
    ) -> str:
        """
        Generate user-friendly denial response from security validation result.

        Reference: LLD 09 Section 5.4

        Args:
            user_query: Original user request
            validation_result: Security Controller validation result
            timeout: Request timeout (shorter for denial messages)

        Returns:
            Natural language denial message
        """
        return self.generate_response(
            user_query=user_query,
            data=validation_result,
            template_type=ResponseTemplate.DENIAL,
            max_tokens=200,  # Short responses for denials
            temperature=0.5,  # Balanced creativity
            timeout=timeout
        )

    def _invoke_bedrock(
        self,
        prompt: str,
        model_id: str,
        max_tokens: int,
        temperature: float
    ) -> str:
        """
        Invoke AWS Bedrock model.

        Args:
            prompt: Formatted prompt
            model_id: Bedrock model ID
            max_tokens: Maximum tokens
            temperature: Temperature setting

        Returns:
            Generated text

        Raises:
            ClientError: If Bedrock invocation fails
        """
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }

        try:
            response = self.bedrock_runtime.invoke_model(
                modelId=model_id,
                body=json.dumps(request_body)
            )

            response_body = json.loads(response['body'].read())

            # Extract text from Claude response
            if 'content' in response_body and len(response_body['content']) > 0:
                return response_body['content'][0]['text']
            else:
                raise ValueError("Invalid response format from Bedrock")

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            logger.error(
                f"Bedrock invocation failed: {error_code}",
                extra={
                    "model_id": model_id,
                    "error": str(e)
                }
            )
            raise

    def _build_prompt(
        self,
        user_query: str,
        data: Union[List[Dict], Dict, str],
        template_type: ResponseTemplate
    ) -> str:
        """
        Build prompt based on template type.

        Reference: LLD 09 Section 5.2, 5.4

        Args:
            user_query: User's original question
            data: Structured data or validation result
            template_type: Type of response template

        Returns:
            Formatted prompt string
        """
        # Convert data to JSON string if needed
        if isinstance(data, (list, dict)):
            data_str = json.dumps(data, indent=2)
        else:
            data_str = str(data)

        # Template dispatch
        if template_type == ResponseTemplate.CUSTOMER_LIST:
            return self._build_customer_list_prompt(user_query, data_str)
        elif template_type == ResponseTemplate.ORDER_LIST:
            return self._build_order_list_prompt(user_query, data_str)
        elif template_type == ResponseTemplate.CUSTOMER_DETAILS:
            return self._build_customer_details_prompt(user_query, data_str)
        elif template_type == ResponseTemplate.ORDER_DETAILS:
            return self._build_order_details_prompt(user_query, data_str)
        elif template_type == ResponseTemplate.REFUND_CONFIRMATION:
            return self._build_refund_confirmation_prompt(user_query, data_str)
        elif template_type == ResponseTemplate.DENIAL:
            return self._build_denial_prompt(user_query, data)
        else:
            return self._build_generic_prompt(user_query, data_str)

    def _build_customer_list_prompt(self, user_query: str, data_str: str) -> str:
        """Build prompt for customer list response"""
        return f"""You are a helpful customer service AI agent. The user asked: "{user_query}"

Here is the data from the database:
{data_str}

Please format this as a natural, friendly response. Include:
- Number of customers found
- Bullet points with name and email for top results (max 5)
- If more than 5, mention "and X more..."
- Keep it concise and professional

Response:"""

    def _build_order_list_prompt(self, user_query: str, data_str: str) -> str:
        """Build prompt for order list response"""
        return f"""You are a helpful customer service AI agent. The user asked: "{user_query}"

Here is the order data from the database:
{data_str}

Please format this as a natural response including:
- Number of orders found
- Summary of key orders (top 5) with order_id, amount, status
- If more than 5, mention "and X more..."
- Keep it concise

Response:"""

    def _build_customer_details_prompt(self, user_query: str, data_str: str) -> str:
        """Build prompt for single customer details"""
        return f"""You are a helpful customer service AI agent. The user asked: "{user_query}"

Here is the customer information:
{data_str}

Please format this as a natural response including:
- Customer name and contact info
- Account details
- Keep it professional and concise

Response:"""

    def _build_order_details_prompt(self, user_query: str, data_str: str) -> str:
        """Build prompt for single order details"""
        return f"""You are a helpful customer service AI agent. The user asked: "{user_query}"

Here is the order information:
{data_str}

Please format this as a natural response including:
- Order number and status
- Amount and items
- Creation date
- Any relevant next steps

Response:"""

    def _build_refund_confirmation_prompt(self, user_query: str, data_str: str) -> str:
        """Build prompt for refund confirmation"""
        return f"""You are a helpful customer service AI agent. The user requested: "{user_query}"

Here is the refund result:
{data_str}

Please format this as a natural confirmation message including:
- Confirmation that the refund was processed
- Amount and order details
- Expected timeline (if available)
- Keep it friendly and reassuring

Response:"""

    def _build_denial_prompt(self, user_query: str, validation_result: Dict) -> str:
        """
        Build prompt for denial response.

        Reference: LLD 09 Section 5.4
        """
        denial_info = {
            "user_request": user_query,
            "decision": validation_result.get('decision'),
            "reason": validation_result.get('reason'),
            "threat_type": validation_result.get('threat_type'),
            "violation_type": validation_result.get('violation_type'),
            "violated_policy": validation_result.get('violated_policy'),
            "rule_id": validation_result.get('rule_id')
        }

        return f"""You are a helpful but security-conscious AI assistant. A user's request was blocked by security controls.

User Request: "{user_query}"

Block Details:
{json.dumps(denial_info, indent=2)}

Generate a natural, professional response that:
1. Politely explains WHY the request was blocked
2. Provides helpful context (e.g., policy limits, security risks)
3. Suggests next steps or alternatives if applicable
4. Maintains a friendly, non-accusatory tone
5. Does NOT include technical jargon or internal system details

Keep it concise (2-3 sentences max).

Response:"""

    def _build_generic_prompt(self, user_query: str, data_str: str) -> str:
        """Build generic prompt for any data type"""
        return f"""You are a helpful AI assistant. Format the following data into a natural, conversational response.

User Query: "{user_query}"

Data:
{data_str}

Instructions:
- Be concise and friendly
- Use natural language, not JSON
- If data is a list, summarize count and show key items (max 5)
- If data is empty, politely say "no results found"
- If data is an error, explain it clearly

Response:"""

    def _fallback_response(
        self,
        data: Union[List[Dict], Dict, str],
        template_type: ResponseTemplate
    ) -> str:
        """
        Generate structured fallback response when LLM fails.

        Args:
            data: Structured data
            template_type: Response template type

        Returns:
            Structured text response
        """
        logger.warning(
            "Using fallback response (LLM unavailable)",
            extra={"template_type": template_type.value}
        )

        # Handle denial responses
        if template_type == ResponseTemplate.DENIAL:
            if isinstance(data, dict):
                reason = data.get('reason', 'Security policy violation')
                return f"⚠️ Request blocked: {reason}"
            return "⚠️ Request blocked by security policy."

        # Handle data responses
        if isinstance(data, list):
            count = len(data)
            if count == 0:
                return "No results found."
            elif count <= 5:
                return f"Found {count} results:\n{json.dumps(data, indent=2)}"
            else:
                return f"Found {count} results:\n{json.dumps(data[:5], indent=2)}\n... and {count - 5} more."

        elif isinstance(data, dict):
            if 'error' in data:
                return f"Error: {data['error']}"
            return json.dumps(data, indent=2)

        else:
            return str(data)


# ==================== Module-level Helper Function ====================

def generate_nlp_response(
    user_query: str,
    data: Union[List[Dict], Dict, str],
    template_type: str = "generic"
) -> str:
    """
    Convenience function for generating NLP responses.

    Args:
        user_query: User's original question
        data: Structured data or validation result
        template_type: Template type (customer_list, order_details, etc.)

    Returns:
        Natural language response
    """
    generator = LLMResponseGenerator()
    return generator.generate_response(user_query, data, template_type)
