"""API Gateway helper functions for creating integrations and common patterns.

This module provides reusable utility functions for API Gateway constructs
that can be shared across multiple CDK stacks.
"""
from aws_cdk import aws_apigateway as apigateway
from typing import Dict, Optional


def create_http_integration(
    alb_base_url: str,
    path: str,
    http_method: str = "POST",
    pass_query_params: Optional[Dict[str, str]] = None,
    include_api_key_header: bool = True
) -> apigateway.HttpIntegration:
    """Create HTTP_PROXY integration to ALB endpoint.

    This helper creates a standard HTTP integration with common request
    parameters like correlation ID and API key ID headers.

    Args:
        alb_base_url: Base URL of the ALB (e.g., 'http://alb-123.us-east-1.elb.amazonaws.com')
        path: API path (e.g., '/v1/validate')
        http_method: HTTP method (POST, GET, etc.)
        pass_query_params: Optional dict mapping query param names to method.request mappings
                          Example: {"session_id": "method.request.querystring.session_id"}
        include_api_key_header: Whether to include X-API-Key-ID header (default: True)

    Returns:
        HttpIntegration configured for the endpoint

    Example:
        >>> integration = create_http_integration(
        ...     alb_base_url="http://my-alb.amazonaws.com",
        ...     path="/v1/validate",
        ...     http_method="POST"
        ... )
    """
    # Standard request parameters for all integrations
    request_params = {
        "integration.request.header.X-Correlation-ID": "context.requestId",
    }

    # Optionally add API key header (not needed for public endpoints like /health)
    if include_api_key_header:
        request_params["integration.request.header.X-API-Key-ID"] = "context.identity.apiKeyId"

    # Add query parameter passthrough if specified
    if pass_query_params:
        for param_name, mapping in pass_query_params.items():
            request_params[f"integration.request.querystring.{param_name}"] = mapping

    return apigateway.HttpIntegration(
        f"{alb_base_url}{path}",
        http_method=http_method,
        options=apigateway.IntegrationOptions(
            connection_type=apigateway.ConnectionType.INTERNET,
            request_parameters=request_params
        )
    )


def create_standard_method_responses(include_500: bool = False) -> list:
    """Create standard method responses for API Gateway endpoints.

    Args:
        include_500: Whether to include 500 Internal Server Error response

    Returns:
        List of MethodResponse objects

    Example:
        >>> responses = create_standard_method_responses(include_500=True)
    """
    responses = [
        apigateway.MethodResponse(
            status_code="200",
            response_models={"application/json": apigateway.Model.EMPTY_MODEL}
        ),
        apigateway.MethodResponse(status_code="400"),
        apigateway.MethodResponse(status_code="403"),
    ]

    if include_500:
        responses.append(apigateway.MethodResponse(status_code="500"))

    return responses


def create_lambda_integration(
    lambda_function,
    request_templates: Optional[Dict[str, str]] = None
) -> apigateway.LambdaIntegration:
    """Create Lambda integration for API Gateway.

    Useful for future stacks that might integrate Lambda functions.

    Args:
        lambda_function: Lambda function to integrate
        request_templates: Optional request templates for integration

    Returns:
        LambdaIntegration configured for the endpoint

    Example:
        >>> integration = create_lambda_integration(my_lambda_function)
    """
    return apigateway.LambdaIntegration(
        lambda_function,
        request_templates=request_templates or {},
        integration_responses=[
            apigateway.IntegrationResponse(status_code="200")
        ]
    )
