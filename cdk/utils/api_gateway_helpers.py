"""API Gateway helper functions for creating integrations and common patterns.

This module provides reusable utility functions for API Gateway constructs
that can be shared across multiple CDK stacks.

Workstream 16 (2026-05-22): switched from ConnectionType.INTERNET (broken — see
LLD 16 §1.2) to ConnectionType.VPC_LINK. Integrations now target the API NLB's
DNS name (NLB → Private ALB → ECS), and every call site must pass the VPC Link
reference. See [LLD 16: API Gateway VPC Link Networking](../../lld/16-apigw-vpc-link-networking.md)
and [ADR-022](../../adr.md#adr-022-fix-rest-api-gateway-via-nlb--vpc-link).
"""
import re

from aws_cdk import aws_apigateway as apigateway
from typing import Dict, Optional


def create_http_integration(
    nlb_base_url: str,
    path: str,
    http_method: str = "POST",
    vpc_link: Optional[apigateway.IVpcLink] = None,
    pass_query_params: Optional[Dict[str, str]] = None,
    include_api_key_header: bool = True,
) -> apigateway.HttpIntegration:
    """Create HTTP_PROXY integration via VPC Link to the API NLB.

    Workstream 16: the previous implementation used `ConnectionType.INTERNET`
    pointing at the Private ALB's internal DNS — which never worked because
    internal DNS isn't routable from API Gateway's public edge. The fix is to
    route via a VPC Link to an NLB that targets the Private ALB.

    Args:
        nlb_base_url: Base URL of the API NLB (e.g.,
            'http://sentra-api-nlb-abcdef.elb.us-east-1.amazonaws.com').
            The NLB's listener forwards to the Private ALB target group, which
            then path-routes to the security-controller target group.
        path: API path (e.g., '/v1/validate').
        http_method: HTTP method (POST, GET, etc.).
        vpc_link: The shared VPC Link from API Stack (`self.api_vpc_link`).
            Required since Workstream 16; pass it from every call site.
        pass_query_params: Optional dict mapping query param names to
            method.request mappings — e.g., {"session_id":
            "method.request.querystring.session_id"}.
        include_api_key_header: Whether to include `X-API-Key-ID` header
            (default True; should be False for public endpoints like /health).

    Returns:
        HttpIntegration configured for the endpoint.

    Example:
        >>> integration = create_http_integration(
        ...     nlb_base_url=self.nlb_base_url,
        ...     path="/v1/validate",
        ...     http_method="POST",
        ...     vpc_link=self.api_vpc_link,
        ... )
    """
    if vpc_link is None:
        raise ValueError(
            "vpc_link is required (Workstream 16). Pass self.api_vpc_link "
            "from the API Stack. See LLD 16 §7.4."
        )

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

    # Map any path parameters in the URI template (e.g. /v1/agents/{agent_id}).
    # WITHOUT this, API Gateway cannot substitute the {param} in the backend URI
    # and returns 500 for EVERY path-parameter endpoint (pre-existing bug — it hit
    # /v1/policies/{id}, /v1/sigma-rules/{id} and all the new WS-21 {param} routes).
    for path_param in re.findall(r"\{([^}]+)\}", path):
        request_params[f"integration.request.path.{path_param}"] = (
            f"method.request.path.{path_param}"
        )

    return apigateway.HttpIntegration(
        f"{nlb_base_url}{path}",
        http_method=http_method,
        options=apigateway.IntegrationOptions(
            connection_type=apigateway.ConnectionType.VPC_LINK,
            vpc_link=vpc_link,
            request_parameters=request_params,
        ),
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
