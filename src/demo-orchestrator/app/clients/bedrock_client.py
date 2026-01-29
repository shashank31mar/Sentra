"""
Bedrock Agent Client
Sentra MVP - Workstream 13, Task 2.2

Uses runtime discovery to find Bedrock agents by name pattern:
- Secured agent: *-customer-service-agent (without -unsecured suffix)
- Unsecured agent: *-customer-service-agent-unsecured
"""

import os
import logging
import boto3
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Agent name patterns for discovery
SECURED_AGENT_PATTERN = "customer-service-agent"
UNSECURED_AGENT_SUFFIX = "-unsecured"


class BedrockAgentClient:
    """Client for invoking AWS Bedrock agents with runtime discovery"""
    
    def __init__(self, region: str = None):
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.bedrock_runtime = boto3.client(
            'bedrock-agent-runtime',
            region_name=self.region
        )
        self.bedrock_agent = boto3.client(
            'bedrock-agent',
            region_name=self.region
        )
        
        # Discovered agent configurations (populated at startup)
        self._agents: Dict[str, Dict[str, str]] = {}
        self._discovery_complete = False
    
    async def discover_agents(self) -> Dict[str, Dict[str, str]]:
        """
        Discover Bedrock agents by name pattern at runtime.
        
        This eliminates the need for hardcoded agent IDs in CDK/env vars.
        
        Returns:
            Dict mapping logical names to agent configs:
            {
                "bedrock-secured": {"agent_id": "ABC123", "alias_id": "TSTALIASID"},
                "bedrock-unsecured": {"agent_id": "XYZ789", "alias_id": "TSTALIASID"}
            }
        """
        if self._discovery_complete:
            return self._agents
        
        logger.info("Discovering Bedrock agents...")
        
        try:
            # List all agents in the account
            paginator = self.bedrock_agent.get_paginator('list_agents')
            
            secured_agent = None
            unsecured_agent = None
            
            for page in paginator.paginate():
                for agent in page.get('agentSummaries', []):
                    agent_name = agent.get('agentName', '')
                    agent_id = agent.get('agentId', '')
                    agent_status = agent.get('agentStatus', '')
                    
                    # Skip agents that aren't prepared
                    if agent_status != 'PREPARED':
                        logger.debug(f"Skipping agent {agent_name} (status: {agent_status})")
                        continue
                    
                    # Check for unsecured agent (must check first - more specific pattern)
                    if SECURED_AGENT_PATTERN in agent_name and agent_name.endswith(UNSECURED_AGENT_SUFFIX):
                        unsecured_agent = {
                            "agent_id": agent_id,
                            "alias_id": "TSTALIASID",  # Default test alias
                            "agent_name": agent_name
                        }
                        logger.info(f"Discovered UNSECURED agent: {agent_name} ({agent_id})")
                    
                    # Check for secured agent (has pattern but NOT unsecured suffix)
                    elif SECURED_AGENT_PATTERN in agent_name and not agent_name.endswith(UNSECURED_AGENT_SUFFIX):
                        secured_agent = {
                            "agent_id": agent_id,
                            "alias_id": "TSTALIASID",  # Default test alias
                            "agent_name": agent_name
                        }
                        logger.info(f"Discovered SECURED agent: {agent_name} ({agent_id})")
            
            # Store discovered agents
            if secured_agent:
                self._agents["bedrock-secured"] = secured_agent
            else:
                logger.warning(f"No secured Bedrock agent found matching pattern '*{SECURED_AGENT_PATTERN}' (without '{UNSECURED_AGENT_SUFFIX}' suffix)")
            
            if unsecured_agent:
                self._agents["bedrock-unsecured"] = unsecured_agent
            else:
                logger.warning(f"No unsecured Bedrock agent found matching pattern '*{SECURED_AGENT_PATTERN}{UNSECURED_AGENT_SUFFIX}'")
            
            self._discovery_complete = True
            logger.info(f"Agent discovery complete. Found {len(self._agents)} agents: {list(self._agents.keys())}")
            
            return self._agents
            
        except Exception as e:
            logger.error(f"Error discovering Bedrock agents: {e}")
            self._discovery_complete = True  # Don't retry on every call
            return self._agents
    
    def get_discovered_agents(self) -> Dict[str, Dict[str, str]]:
        """Get the discovered agents (call discover_agents first)"""
        return self._agents
    
    def is_agent_available(self, agent_name: str) -> bool:
        """Check if an agent was discovered and is available"""
        return agent_name in self._agents and bool(self._agents[agent_name].get("agent_id"))
    
    async def invoke_agent(
        self,
        agent_name: str,
        session_id: str,
        input_text: str
    ) -> Dict[str, Any]:
        """
        Invoke Bedrock agent and return response
        
        Args:
            agent_name: Agent identifier (bedrock-secured, bedrock-unsecured)
            session_id: Unique session ID for conversation
            input_text: User prompt text
        
        Returns:
            Dict with output_text and tool_invocations
        """
        # Ensure discovery has run
        if not self._discovery_complete:
            await self.discover_agents()
        
        agent_config = self._agents.get(agent_name)
        
        if not agent_config or not agent_config.get("agent_id"):
            logger.warning(f"Agent {agent_name} not discovered/available, skipping")
            return {
                "output_text": f"Agent {agent_name} not available",
                "tool_invocations": [],
                "error": "Agent not discovered"
            }
        
        try:
            logger.info(
                f"Invoking Bedrock agent",
                extra={
                    "agent_name": agent_name,
                    "agent_id": agent_config["agent_id"],
                    "discovered_name": agent_config.get("agent_name"),
                    "session_id": session_id
                }
            )
            
            response = self.bedrock_runtime.invoke_agent(
                agentId=agent_config["agent_id"],
                agentAliasId=agent_config["alias_id"],
                sessionId=session_id,
                inputText=input_text
            )
            
            # Process streaming response
            output_text = ""
            tool_invocations = []
            
            for event in response.get('completion', []):
                if 'chunk' in event:
                    chunk = event['chunk']
                    if 'bytes' in chunk:
                        output_text += chunk['bytes'].decode('utf-8')
                
                if 'trace' in event:
                    trace = event['trace'].get('trace', {})
                    tools = self._extract_tools_from_trace(trace)
                    tool_invocations.extend(tools)
            
            logger.info(
                f"Bedrock agent response received",
                extra={
                    "agent_name": agent_name,
                    "output_length": len(output_text),
                    "tool_count": len(tool_invocations)
                }
            )
            
            return {
                "output_text": output_text,
                "tool_invocations": tool_invocations
            }
            
        except self.bedrock_runtime.exceptions.ThrottlingException:
            logger.warning(f"Bedrock throttling for {agent_name}")
            return {
                "output_text": "",
                "tool_invocations": [],
                "error": "ThrottlingException"
            }
        except Exception as e:
            logger.error(f"Error invoking Bedrock agent {agent_name}: {e}")
            return {
                "output_text": "",
                "tool_invocations": [],
                "error": str(e)
            }
    
    def _extract_tools_from_trace(self, trace: Dict) -> List[Dict]:
        """Extract tool invocations from Bedrock trace"""
        tools = []
        
        # Check orchestration trace for tool calls
        orchestration = trace.get('orchestrationTrace', {})
        
        # Model invocation input may contain tool use
        model_input = orchestration.get('modelInvocationInput', {})
        if model_input:
            tools.append({
                "type": "model_invocation",
                "input": model_input.get('text', '')[:200]
            })
        
        # Invocation input shows actual tool calls
        invocation = orchestration.get('invocationInput', {})
        if invocation:
            action_group = invocation.get('actionGroupInvocationInput', {})
            if action_group:
                tools.append({
                    "type": "action_group",
                    "action_group": action_group.get('actionGroupName', ''),
                    "function": action_group.get('function', ''),
                    "parameters": action_group.get('parameters', [])
                })
        
        # Observation shows tool results
        observation = orchestration.get('observation', {})
        if observation:
            action_result = observation.get('actionGroupInvocationOutput', {})
            if action_result:
                tools.append({
                    "type": "action_result",
                    "text": action_result.get('text', '')[:500]
                })
        
        return tools
