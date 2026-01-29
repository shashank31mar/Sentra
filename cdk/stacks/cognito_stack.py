"""
Sentra MVP - Cognito Stack
Creates AWS Cognito User Pool for Dashboard authentication

Reference: LLD 08 Section 5.1
"""

from aws_cdk import (
    Stack,
    RemovalPolicy,
    CfnOutput,
    Duration,
    aws_cognito as cognito,
)
from constructs import Construct
from typing import Dict, Any, Optional


class CognitoStack(Stack):
    """
    Cognito Stack - User Authentication

    Creates:
    - Cognito User Pool
    - User Pool Client (for ALB integration)
    - User Pool Domain (hosted UI)

    Exports:
    - User Pool ID and ARN
    - User Pool Client ID
    - User Pool Domain
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config: Dict[str, Any],
        alb_dns_name: Optional[str] = None,
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        cognito_config = config.get("cognito", {})
        naming_config = config.get("naming", {})
        prefix = naming_config.get("prefix", "sentra-mvp")

        # Create User Pool
        self.user_pool = cognito.UserPool(
            self,
            "DashboardUserPool",
            user_pool_name=cognito_config.get("user_pool_name", "sentra-dashboard-users"),
            
            # Sign-in configuration
            self_sign_up_enabled=False,  # Admin creates users
            sign_in_aliases=cognito.SignInAliases(
                email=True,
                username=False
            ),
            
            # Password policy
            password_policy=cognito.PasswordPolicy(
                min_length=cognito_config.get("password_min_length", 12),
                require_uppercase=True,
                require_lowercase=True,
                require_digits=True,
                require_symbols=True,
                temp_password_validity=Duration.days(7)
            ),
            
            # Account recovery
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            
            # MFA (optional)
            mfa=cognito.Mfa.OPTIONAL if cognito_config.get("mfa_enabled", False) else cognito.Mfa.OFF,
            
            # Email configuration
            email=cognito.UserPoolEmail.with_cognito(),
            
            # User attributes
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(
                    required=True,
                    mutable=True
                )
            ),
            
            # Cleanup
            removal_policy=RemovalPolicy.DESTROY
        )

        # Create User Pool Client (for ALB)
        self.user_pool_client = cognito.UserPoolClient(
            self,
            "DashboardUserPoolClient",
            user_pool=self.user_pool,
            user_pool_client_name="sentra-dashboard-alb-client",

            # OAuth configuration (required for ALB)
            # IMPORTANT: ALB REQUIRES client secret for Cognito authentication
            # The secret is stored in AWS Secrets Manager and retrieved by ALB automatically
            generate_secret=True,  # ALB requires client secret
            
            # Auth flows
            auth_flows=cognito.AuthFlow(
                user_password=True,
                user_srp=True,
                admin_user_password=True
            ),
            
            # OAuth settings
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(
                    authorization_code_grant=True
                ),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE
                ],
                callback_urls=self._get_callback_urls(alb_dns_name),
                logout_urls=self._get_logout_urls(alb_dns_name)
            ),
            
            # Token validity
            id_token_validity=Duration.hours(1),
            access_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(30),
            
            # Security
            prevent_user_existence_errors=True
        )

        # Create Cognito Domain (hosted UI)
        self.user_pool_domain = cognito.UserPoolDomain(
            self,
            "DashboardUserPoolDomain",
            user_pool=self.user_pool,
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=cognito_config.get("domain_prefix", "sentra-dashboard-mvp")
            )
        )

        # CloudFormation Outputs
        CfnOutput(
            self,
            "UserPoolId",
            value=self.user_pool.user_pool_id,
            description="Cognito User Pool ID",
            export_name=f"{prefix}-user-pool-id",
        )

        CfnOutput(
            self,
            "UserPoolArn",
            value=self.user_pool.user_pool_arn,
            description="Cognito User Pool ARN",
            export_name=f"{prefix}-user-pool-arn",
        )

        CfnOutput(
            self,
            "UserPoolClientId",
            value=self.user_pool_client.user_pool_client_id,
            description="Cognito User Pool Client ID",
            export_name=f"{prefix}-user-pool-client-id",
        )

        CfnOutput(
            self,
            "UserPoolDomain",
            value=self.user_pool_domain.domain_name,
            description="Cognito User Pool Domain",
            export_name=f"{prefix}-user-pool-domain",
        )

    def _get_callback_urls(self, alb_dns_name: Optional[str]) -> list:
        """
        Get callback URLs for Cognito User Pool Client.
        
        If ALB DNS is provided, use it. Otherwise, use placeholder.
        Cognito requires HTTPS for callback URLs (except localhost).
        """
        if alb_dns_name:
            return [
                f"https://{alb_dns_name}/oauth2/idpresponse",
            ]
        else:
            # Placeholder for initial deployment
            # Will be updated via Custom Resource after ALB is created
            return ["https://localhost/oauth2/idpresponse"]

    def _get_logout_urls(self, alb_dns_name: Optional[str]) -> list:
        """
        Get logout URLs for Cognito User Pool Client.
        
        If ALB DNS is provided, use it. Otherwise, use placeholder.
        """
        if alb_dns_name:
            return [
                f"https://{alb_dns_name}/",
            ]
        else:
            # Placeholder for initial deployment
            return ["https://localhost/"]

    # Note: update_callback_urls() method removed to avoid circular dependency
    # The Custom Resource to update callback URLs is now in Compute Stack
