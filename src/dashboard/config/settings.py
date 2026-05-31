"""
Configuration settings for Sentra Dashboard.
Loads environment-specific configuration.
"""
import os
from typing import Optional


class Settings:
    """Dashboard configuration settings."""
    
    def __init__(self):
        # Environment
        self.environment = os.getenv("ENVIRONMENT", "dev")
        
        # AWS Configuration
        self.aws_region = os.getenv("AWS_REGION", "us-east-1")
        self.aws_profile = os.getenv("AWS_PROFILE", "sentra")
        
        # Security Controller
        # Uses Cloud Map service discovery for internal communication
        self.security_controller_url = os.getenv(
            "SECURITY_CONTROLLER_URL",
            "http://security-controller.sentra.internal:8080"
        )
        
        # Demo Orchestrator
        self.demo_orchestrator_url = os.getenv(
            "DEMO_ORCHESTRATOR_URL",
            "http://demo-orchestrator.sentra.internal:8080"
        )
        
        # Logging
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        
        # Dashboard Settings
        self.page_title = "AegionAI Prototype - AI Agent Security Platform"
        self.page_icon = "🛡️"
        self.auto_refresh_interval = 1  # seconds for Overview tab
        self.slow_refresh_interval = 5  # seconds for other tabs
        
        # DynamoDB Tables
        self.session_context_table = os.getenv(
            "SESSION_CONTEXT_TABLE",
            "sentra-session-context"
        )
        self.policies_table = os.getenv(
            "POLICIES_TABLE",
            "sentra-policies"
        )
        
        # CloudWatch Logs
        self.audit_log_group = os.getenv(
            "AUDIT_LOG_GROUP",
            "/sentra/audit-logs"
        )
    
    def get_security_controller_endpoint(self, path: str) -> str:
        """Get full Security Controller endpoint URL."""
        return f"{self.security_controller_url}{path}"


# Global settings instance
settings = Settings()
