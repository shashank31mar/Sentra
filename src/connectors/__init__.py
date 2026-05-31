"""
Cross-cloud agent connectors.

Each connector implements AgentConnector for a specific cloud platform
(AWS Bedrock, Azure AI Foundry, GCP Vertex AI). The security controller
(/v1/validate) is platform-agnostic; connectors handle only the cloud-specific
translation between native agent events and ValidationRequest.
"""
