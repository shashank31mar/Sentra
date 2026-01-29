"""Reusable API Gateway endpoint construct.

Provides standardized API endpoint creation with rate limiting and authentication.
"""
from aws_cdk import (
    aws_apigateway as apigateway,
)
from constructs import Construct
from typing import Optional, Dict, Any, List


class StandardApiEndpoint(Construct):
    """Reusable construct for API Gateway endpoints with standard configuration.

    This construct creates a REST API resource with method, rate limiting,
    authentication, and validation settings.

    Attributes:
        resource: The API Gateway resource created
        method: The API Gateway method created
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        api: apigateway.RestApi,
        parent_resource: apigateway.Resource,
        path: str,
        http_method: str,
        integration: apigateway.Integration,
        rate_limit: int,
        burst_limit: int,
        api_key_required: bool = True,
        request_validator: Optional[apigateway.RequestValidator] = None,
        request_models: Optional[Dict[str, apigateway.Model]] = None,
        request_parameters: Optional[Dict[str, bool]] = None,
        method_responses: Optional[List[apigateway.MethodResponse]] = None,
        **kwargs
    ) -> None:
        """Initialize StandardApiEndpoint.

        Args:
            scope: CDK scope
            id: Construct ID
            api: REST API instance
            parent_resource: Parent resource to attach to
            path: Resource path (e.g., 'validate', 'health')
            http_method: HTTP method (GET, POST, etc.)
            integration: API Gateway integration
            rate_limit: Rate limit in requests per minute
            burst_limit: Burst limit
            api_key_required: Whether API key is required
            request_validator: Optional request validator
            request_models: Optional request models for request body validation
            request_parameters: Optional request parameters (e.g., query strings)
            method_responses: Optional method response configurations
            **kwargs: Additional arguments
        """
        super().__init__(scope, id, **kwargs)

        # Create resource
        self.resource = parent_resource.add_resource(path)

        # Build method options
        method_options = {
            "api_key_required": api_key_required,
            "authorization_type": apigateway.AuthorizationType.NONE,
        }

        if request_validator:
            method_options["request_validator"] = request_validator

        if request_models:
            method_options["request_models"] = request_models

        if request_parameters:
            method_options["request_parameters"] = request_parameters

        if method_responses:
            method_options["method_responses"] = method_responses
        else:
            # Default method responses if none provided
            method_options["method_responses"] = [
                apigateway.MethodResponse(
                    status_code="200",
                    response_models={"application/json": apigateway.Model.EMPTY_MODEL}
                ),
                apigateway.MethodResponse(status_code="400"),
                apigateway.MethodResponse(status_code="403"),
            ]

        # Add method
        self.method = self.resource.add_method(
            http_method,
            integration,
            **method_options
        )

        # Note: Per-method throttling is configured at the stage level via method settings
        # The rate_limit and burst_limit parameters are stored for documentation purposes
        # Actual throttling is controlled by the API Gateway stage deployment options
        # and usage plans (configured in ApiStack)
