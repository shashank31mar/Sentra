"""Configuration loader for Sentra MVP CDK stacks.

Loads environment-specific configuration from YAML files.
"""
import yaml
import os
from typing import Any, Dict, Optional


class Config:
    """Configuration loader for environment-specific settings."""

    def __init__(self, env: str = "dev"):
        """Initialize configuration loader.

        Args:
            env: Environment name (dev, staging, prod)
        """
        self.env = env
        config_path = os.path.join(
            os.path.dirname(__file__),
            f"{env}.yaml"
        )

        if not os.path.exists(config_path):
            raise FileNotFoundError(
                f"Configuration file not found: {config_path}. "
                f"Available environments: dev, staging, prod"
            )

        with open(config_path, 'r') as f:
            self._config = yaml.safe_load(f)

    def get(self, key_path: str, default: Any = None) -> Any:
        """Get configuration value by dot-notation path.

        Args:
            key_path: Dot-notation path (e.g., 'api_gateway.endpoints.health.rate_limit')
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        keys = key_path.split('.')
        value = self._config

        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default

        return value

    # AWS Configuration
    @property
    def aws_account_id(self) -> Optional[str]:
        """Get AWS account ID from config or environment."""
        return os.environ.get('AWS_ACCOUNT_ID') or self.get('aws.account_id')

    @property
    def aws_region(self) -> str:
        """Get AWS region."""
        return os.environ.get('AWS_REGION') or self.get('aws.region', 'us-east-1')

    @property
    def aws_profile(self) -> str:
        """Get AWS profile name."""
        return os.environ.get('AWS_PROFILE') or self.get('aws.profile', 'sentra')

    # API Gateway Configuration
    def get_api_gateway_config(self, key: str, default: Any = None) -> Any:
        """Get API Gateway configuration value."""
        return self.get(f'api_gateway.{key}', default)

    def get_endpoint_config(self, endpoint: str, key: str, default: Any = None) -> Any:
        """Get endpoint-specific configuration."""
        return self.get(f'api_gateway.endpoints.{endpoint}.{key}', default)

    def get_endpoint_rate_limit(self, endpoint: str) -> int:
        """Get rate limit for specific endpoint."""
        return self.get_endpoint_config(endpoint, 'rate_limit', 100)

    def get_endpoint_burst_limit(self, endpoint: str) -> int:
        """Get burst limit for specific endpoint."""
        return self.get_endpoint_config(endpoint, 'burst_limit', 200)

    def get_endpoint_auth_required(self, endpoint: str) -> bool:
        """Get auth requirement for specific endpoint."""
        return self.get_endpoint_config(endpoint, 'auth_required', True)

    # Monitoring Configuration
    def get_monitoring_config(self, key: str, default: Any = None) -> Any:
        """Get monitoring configuration value."""
        return self.get(f'monitoring.{key}', default)
