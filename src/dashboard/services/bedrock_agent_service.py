"""
Bedrock Agent Service - Discover and list AWS Bedrock agents.

Provides runtime discovery of Bedrock agents by name pattern:
- Secured: *-customer-service-agent (without -unsecured suffix)
- Unsecured: *-customer-service-agent-unsecured

Reuses the same discovery logic as demo-orchestrator/app/clients/bedrock_client.py
"""
import boto3
import logging
import os
from typing import Dict, List, Optional
import time

logger = logging.getLogger(__name__)

# Agent name patterns for discovery (same as demo-orchestrator).
# Three flavors of the customer-service agent:
#   *-customer-service-agent            -> secured (Claude + guardrail + Sentra-calling Lambda)
#   *-customer-service-agent-unsecured  -> unsecured (Nova Lite + direct Lambda, NO Sentra)
#   *-customer-service-agent-naive      -> naive (Nova Lite + Sentra-calling Lambda, no guardrail)
# Naive demonstrates the "Sentra protects even a misconfigured agent" story
# (Workstream 15 M5 defense-in-depth narrative).
SECURED_AGENT_PATTERN = "customer-service-agent"
UNSECURED_AGENT_SUFFIX = "-unsecured"
NAIVE_AGENT_SUFFIX = "-naive"


class BedrockAgentService:
    """Service for discovering and managing Bedrock agents."""

    def __init__(self, region: str = None):
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.bedrock_agent = boto3.client('bedrock-agent', region_name=self.region)
        self._cache: Dict[str, List[Dict]] = {}
        self._cache_time = 0
        self._cache_ttl = 60  # Cache for 60 seconds

    def discover_agents(self) -> List[Dict]:
        """
        Discover Bedrock agents by name pattern at runtime.
        
        Uses same pattern matching as demo-orchestrator:
        - Secured: *-customer-service-agent (without -unsecured suffix)
        - Unsecured: *-customer-service-agent-unsecured
        
        Returns:
            List of agent dicts with id, name, status, type (secured/unsecured)
        """
        # Check cache
        if self._cache.get('agents') and (time.time() - self._cache_time) < self._cache_ttl:
            return self._cache['agents']

        agents = []
        
        try:
            logger.info("Discovering Bedrock agents...")
            paginator = self.bedrock_agent.get_paginator('list_agents')
            
            for page in paginator.paginate():
                for agent in page.get('agentSummaries', []):
                    agent_name = agent.get('agentName', '')
                    agent_id = agent.get('agentId', '')
                    status = agent.get('agentStatus', 'UNKNOWN')
                    
                    # Skip agents that aren't prepared (same logic as demo-orchestrator)
                    if status != 'PREPARED':
                        logger.debug(f"Skipping agent {agent_name} (status: {status})")
                        continue
                    
                    # Determine agent type based on name pattern
                    security_type = None
                    display_name = agent_name
                    
                    # Check most-specific suffix first; bare pattern is the default.
                    if SECURED_AGENT_PATTERN in agent_name:
                        if agent_name.endswith(UNSECURED_AGENT_SUFFIX):
                            security_type = "unsecured"
                            display_name = "Bedrock Unsecured Agent"
                        elif agent_name.endswith(NAIVE_AGENT_SUFFIX):
                            security_type = "naive"
                            display_name = "Bedrock Naive Agent (Sentra-protected)"
                        else:
                            security_type = "secured"
                            display_name = "Bedrock Secured Agent"
                    
                    # Only include Sentra-related agents
                    if security_type:
                        agents.append({
                            'id': agent_id,
                            'name': display_name,
                            'raw_name': agent_name,
                            'status': status.lower(),
                            'security_type': security_type,
                            'alias_id': 'TSTALIASID',  # Default test alias
                        })
                        logger.info(f"Discovered {security_type.upper()} agent: {agent_name} ({agent_id})")
            
            # Sort: secured first, then unsecured
            agents.sort(key=lambda x: (0 if x['security_type'] == 'secured' else 1, x['name']))
            
            # Update cache
            self._cache['agents'] = agents
            self._cache_time = time.time()
            
            logger.info(f"Agent discovery complete. Found {len(agents)} Bedrock agents")
            return agents
            
        except Exception as e:
            logger.error(f"Error discovering Bedrock agents: {e}")
            return []

    def get_agent(self, agent_id: str) -> Optional[Dict]:
        """Get details for a specific agent by ID."""
        agents = self.discover_agents()
        for agent in agents:
            if agent['id'] == agent_id:
                return agent
        return None

    def get_agent_by_type(self, security_type: str) -> Optional[Dict]:
        """Get agent by security type (secured/unsecured)."""
        agents = self.discover_agents()
        for agent in agents:
            if agent['security_type'] == security_type:
                return agent
        return None


# Singleton instance
_service_instance: Optional[BedrockAgentService] = None


def get_bedrock_agent_service() -> BedrockAgentService:
    """Get singleton instance of BedrockAgentService."""
    global _service_instance
    if _service_instance is None:
        _service_instance = BedrockAgentService()
    return _service_instance
