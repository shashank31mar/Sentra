"""
Security Controller Client - HTTP client for Security Controller API.

All Dashboard data access goes through this client to Security Controller APIs.
Dashboard does NOT directly access CloudWatch or DynamoDB.
"""
import requests
from typing import Dict, List, Optional
from datetime import datetime
import logging
import streamlit as st

from config.settings import settings

logger = logging.getLogger(__name__)


def _get_operator_context() -> Dict[str, str]:
    """
    Get operator context for audit logging.
    
    Returns:
        Dict with operator_email and operator_source for audit trail.
    """
    try:
        # Import here to avoid circular imports
        from utils.auth import get_user_email
        return {
            'operator_email': get_user_email(),
            'operator_source': 'dashboard'
        }
    except Exception as e:
        logger.warning(f"Could not get operator context: {e}")
        return {
            'operator_email': 'unknown',
            'operator_source': 'dashboard'
        }


class SecurityControllerClient:
    """Client for interacting with Security Controller API."""
    
    def __init__(self):
        self.base_url = settings.security_controller_url
        # Default timeout for fast endpoints (/v1/health, /v1/agents simple list).
        self.timeout = 5  # seconds
        # /v1/logs queries CloudWatch Logs Insights which can take 5-15s under
        # cold-start conditions. The cross-cloud demo runner's audit-lookup
        # uses this — too aggressive a timeout means the runner misses the
        # controller's authoritative decision and shows the stale invoker view.
        self.logs_timeout = 30  # seconds
    
    def get_health(self, agent_id: Optional[str] = None) -> Dict:
        """
        Get health status of Security Controller or specific agent.
        
        Args:
            agent_id: Optional agent ID to check specific agent health.
        
        Returns:
            Dictionary with health status.
        """
        try:
            url = f"{self.base_url}/v1/health"
            params = {"agent_id": agent_id} if agent_id else {}
            
            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            
            return response.json()
        
        except requests.exceptions.Timeout:
            logger.error(f"Timeout connecting to Security Controller: {url}")
            return {
                "status": "error",
                "message": "Connection timeout",
                "timestamp": datetime.utcnow().isoformat()
            }
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Error connecting to Security Controller: {e}")
            return {
                "status": "error",
                "message": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    def get_logs(
        self,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 100,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        decision: Optional[str] = None,
        threat_type: Optional[str] = None
    ) -> Dict:
        """
        Get audit logs from Security Controller.
        
        Args:
            since: Start time (ISO 8601 timestamp).
            until: End time (ISO 8601 timestamp).
            limit: Maximum number of logs to return.
            session_id: Filter by session ID.
            agent_id: Filter by agent ID.
            decision: Filter by decision (ALLOW/DENY).
            threat_type: Filter by threat type.
        
        Returns:
            Dict with success, status_code, logs, total, has_more, error (if failed).
        """
        try:
            url = f"{self.base_url}/v1/logs"
            params = {"limit": limit}
            
            if since:
                params["since"] = since
            if until:
                params["until"] = until
            if session_id:
                params["session_id"] = session_id
            if agent_id:
                params["agent_id"] = agent_id
            if decision:
                params["decision"] = decision
            if threat_type:
                params["threat_type"] = threat_type

            # /v1/logs is slow (CloudWatch Logs Insights). Use logs_timeout
            # not the default self.timeout — see __init__ rationale.
            response = requests.get(url, params=params, timeout=self.logs_timeout)

            # Check status code
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "status_code": 200,
                    "logs": data.get("logs", []),
                    "total": data.get("total", 0),
                    "has_more": data.get("has_more", False),
                }
            else:
                logger.error(f"API returned status {response.status_code}: {response.text}")
                return {
                    "success": False,
                    "status_code": response.status_code,
                    "logs": [],
                    "error": f"HTTP {response.status_code}: {response.text[:100]}",
                }
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching logs from Security Controller: {e}")
            return {
                "success": False,
                "status_code": 0,
                "logs": [],
                "error": str(e),
            }
    
    def get_session_decisions(
        self,
        session_id: str,
        request_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 100,
    ) -> Dict:
        """Get combined-decision rows for a session — Workstream 17 / LLD 17 §8.2.

        Returns the same shape as GET /v1/sessions/{id}/decisions:
            { "session_id": "...", "decisions": [...], "total": N }

        Used by the cross-cloud runner's decisions_lookup_fn. Sub-100ms p95
        (single DDB partition Query) — much faster than the legacy
        /v1/logs path (CloudWatch Insights, 60s+ indexing lag).
        """
        try:
            url = f"{self.base_url}/v1/sessions/{session_id}/decisions"
            params: Dict[str, object] = {"limit": limit}
            if request_id:
                params["request_id"] = request_id
            if agent_id:
                params["agent_id"] = agent_id
            # Decisions endpoint is fast — DDB-backed, ~100ms p95 — so the
            # standard timeout is plenty. No need for logs_timeout.
            response = requests.get(url, params=params, timeout=self.timeout)
            if response.status_code == 200:
                return response.json()
            logger.error(
                "get_session_decisions: status=%s body=%s",
                response.status_code, response.text[:200],
            )
            return {"session_id": session_id, "decisions": [], "total": 0}
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching session decisions: {e}")
            return {"session_id": session_id, "decisions": [], "total": 0}

    def post_session_signal(
        self,
        session_id: str,
        signal: Dict,
    ) -> Dict:
        """POST an externally-produced signal — Workstream 17 / LLD 17 §8.1.

        Used by connectors to emit edge signals (bedrock_guardrail,
        azure_content_filter). Returns the controller's response on 201,
        or an error dict otherwise. Never raises into the caller.
        """
        try:
            url = f"{self.base_url}/v1/sessions/{session_id}/signals"
            response = requests.post(
                url, json=signal, timeout=self.timeout,
                headers={"Content-Type": "application/json"},
            )
            if response.status_code in (200, 201):
                return response.json()
            return {"error": f"HTTP {response.status_code}: {response.text[:200]}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"Error posting signal: {e}")
            return {"error": str(e)}

    def get_sessions(
        self,
        status: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 50
    ) -> Dict:
        """
        Get sessions from Security Controller.
        
        Args:
            status: Filter by quarantine status (active/quarantined/suspended).
            agent_id: Filter by agent ID.
            limit: Maximum number of sessions to return.
        
        Returns:
            Dict with sessions array and total count.
        """
        try:
            url = f"{self.base_url}/v1/sessions"
            params = {"limit": limit}
            
            if status:
                params["status"] = status
            if agent_id:
                params["agent_id"] = agent_id
            
            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            
            return response.json()
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching sessions from Security Controller: {e}")
            return {"sessions": [], "total": 0}
    
    def get_metrics(
        self,
        since: Optional[str] = None,
        until: Optional[str] = None
    ) -> Dict:
        """
        Get summary metrics from Security Controller.
        
        Args:
            since: Start time (ISO 8601 timestamp).
            until: End time (ISO 8601 timestamp).
        
        Returns:
            Dict with success, status_code, metrics, error (if failed).
        """
        try:
            url = f"{self.base_url}/v1/metrics"
            params = {}
            
            if since:
                params["since"] = since
            if until:
                params["until"] = until
            
            response = requests.get(url, params=params, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "status_code": 200,
                    "metrics": data,
                }
            else:
                logger.error(f"API returned status {response.status_code}: {response.text}")
                return {
                    "success": False,
                    "status_code": response.status_code,
                    "error": f"HTTP {response.status_code}",
                }
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching metrics from Security Controller: {e}")
            return {
                "success": False,
                "status_code": 0,
                "error": str(e),
            }
    
    def rollback_action(
        self,
        request_id: str,
        reason: str,
        operator_id: str = None
    ) -> Dict:
        """
        Rollback a previously executed action.
        
        Args:
            request_id: ID of the request to rollback.
            reason: Reason for rollback.
            operator_id: ID of the operator performing rollback (auto-filled from auth).
        
        Returns:
            Dict with success, status_code, message, error (if failed).
        """
        try:
            url = f"{self.base_url}/v1/rollback"
            
            # Get operator context for audit trail
            operator_context = _get_operator_context()
            
            payload = {
                "request_id": request_id,
                "reason": reason,
                "operator_id": operator_id or operator_context['operator_email'],
                "operator_email": operator_context['operator_email'],
                "operator_source": operator_context['operator_source'],
                "timestamp": datetime.utcnow().isoformat()
            }
            
            response = requests.post(url, json=payload, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "status_code": 200,
                    "message": data.get("message", "Rollback successful"),
                }
            else:
                logger.error(f"API returned status {response.status_code}: {response.text}")
                return {
                    "success": False,
                    "status_code": response.status_code,
                    "error": f"HTTP {response.status_code}: {response.text[:100]}",
                }
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Error performing rollback: {e}")
            return {
                "success": False,
                "status_code": 0,
                "error": str(e),
            }
    
    def validate_request(
        self,
        request_id: str,
        agent_id: str,
        session_id: str,
        user_input: str,
        tool_name: str,
        tool_params: Dict,
        operation_type: str
    ) -> Dict:
        """
        Validate a request through Security Controller.

        Args:
            request_id: Unique request identifier.
            agent_id: ID of the agent making the request.
            session_id: Session ID.
            user_input: User's input message.
            tool_name: Name of the tool to execute.
            tool_params: Parameters for the tool.
            operation_type: Operation type (READ or WRITE).

        Returns:
            Dictionary with validation result.
        """
        try:
            url = f"{self.base_url}/v1/validate"

            payload = {
                "request_id": request_id,
                "agent_id": agent_id,
                "session_id": session_id,
                "user_input": user_input,
                "tool_name": tool_name,
                "tool_params": tool_params,
                "operation_type": operation_type,
                "timestamp": datetime.utcnow().isoformat() + 'Z'
            }

            response = requests.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()

            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"Error validating request: {e}")
            return {
                "decision": "DENY",
                "reason": f"Security Controller error: {str(e)}",
                "threat_type": "SYSTEM_ERROR"
            }

    # ============================================================
    # Agent Management APIs (LLD 05)
    # ============================================================

    def get_agents(self) -> Dict:
        """
        Get list of all agents (fast, no enrichment).
        
        Use this for dropdowns, filters, and simple agent lists.
        For status panels needing uptime/trust scores, use get_agents_enriched().

        Returns:
            Dict with agents array and total count.
        """
        try:
            url = f"{self.base_url}/v1/agents"
            # Explicitly request non-enriched data for fast response
            response = requests.get(url, params={"enrich": "false"}, timeout=self.timeout)
            response.raise_for_status()

            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching agents: {e}")
            return {"agents": [], "total": 0}

    def get_agents_enriched(self) -> Dict:
        """
        Get all agents with runtime statistics (slower).
        
        Use this for agent status panels that need uptime, trust scores, etc.
        For simple agent lists/dropdowns, use get_agents() instead.

        Returns:
            Dict with enriched agents array and total count.
        """
        try:
            url = f"{self.base_url}/v1/agents"
            # Longer timeout for enriched data
            response = requests.get(url, params={"enrich": "true"}, timeout=30)
            response.raise_for_status()

            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching enriched agents: {e}")
            return {"agents": [], "total": 0}

    def get_agent_details(self, agent_id: str) -> Optional[Dict]:
        """
        Get detailed information about a specific agent.

        Args:
            agent_id: Agent identifier.

        Returns:
            Agent details dictionary or None if not found.
        """
        try:
            url = f"{self.base_url}/v1/agents/{agent_id}"
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()

            return response.json()

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.warning(f"Agent {agent_id} not found")
                return None
            logger.error(f"Error fetching agent details: {e}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching agent details: {e}")
            return None

    def get_agent_tools(self, agent_id: str) -> Dict:
        """
        Get allowed tools for a specific agent.

        Args:
            agent_id: Agent identifier.

        Returns:
            Dict with tools array and total count.
        """
        try:
            url = f"{self.base_url}/v1/agents/{agent_id}/tools"
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()

            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching agent tools for {agent_id}: {e}")
            return {"agent_id": agent_id, "tools": [], "total": 0}

    def get_policies(
        self,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50
    ) -> Dict:
        """
        Query agent policies with optional filters.

        Args:
            agent_id: Filter by agent ID.
            status: Filter by status (active, disabled, warning).
            limit: Maximum number of policies to return.

        Returns:
            Dict with policies array, total, and has_more flag.
        """
        try:
            url = f"{self.base_url}/v1/policies"
            params = {"limit": limit}

            if agent_id:
                params["agent_id"] = agent_id
            if status:
                params["status"] = status

            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()

            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching policies: {e}")
            return {"policies": [], "total": 0, "has_more": False}

    def get_sigma_rules(
        self,
        status: Optional[str] = None,
        level: Optional[str] = None,
        limit: int = 50,
        match_range: str = "24h"
    ) -> Dict:
        """
        Get list of Sigma rules with match counts.

        Args:
            status: Filter by status (stable, experimental, deprecated).
            level: Filter by severity level (critical, high, medium, low).
            limit: Maximum number of rules to return.
            match_range: Match-count time window (1h, 24h, 7d, 30d).

        Returns:
            Dict with success, status_code, rules, total, has_more, error (if failed).
        """
        try:
            url = f"{self.base_url}/v1/sigma-rules"
            params = {"limit": limit, "range": match_range}

            if status:
                params["status"] = status
            if level:
                params["level"] = level

            response = requests.get(url, params=params, timeout=self.timeout)

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "status_code": 200,
                    "rules": data.get("rules", []),
                    "total": data.get("total", 0),
                    "has_more": data.get("has_more", False),
                }
            else:
                logger.error(f"API returned status {response.status_code}: {response.text}")
                return {
                    "success": False,
                    "status_code": response.status_code,
                    "rules": [],
                    "error": f"HTTP {response.status_code}",
                }

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching Sigma rules: {e}")
            return {
                "success": False,
                "status_code": 0,
                "rules": [],
                "error": str(e),
            }

    def update_sigma_rule_status(self, rule_id: str, new_status: str) -> Dict:
        """Update Sigma rule status (enable/disable)."""
        try:
            url = f"{self.base_url}/v1/sigma-rules/{rule_id}"
            resp = requests.patch(url, json={'status': new_status}, timeout=self.timeout)
            if resp.status_code == 200:
                return {"success": True, "data": resp.json()}
            else:
                return {"success": False, "error": f"HTTP {resp.status_code}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"Error updating sigma rule: {e}")
            return {"success": False, "error": str(e)}

    def get_sigma_rule_content(self, rule_id: str) -> Dict:
        """Get a Sigma rule's detection selections/patterns for the detail view."""
        try:
            url = f"{self.base_url}/v1/sigma-rules/{rule_id}/content"
            resp = requests.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                return {"success": True, "data": resp.json()}
            return {"success": False, "error": f"HTTP {resp.status_code}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching sigma rule content: {e}")
            return {"success": False, "error": str(e)}

    # ============================================================
    # Workstream 11: Policy CRUD Methods
    # ============================================================

    def get_policy_by_id(
        self,
        policy_id: str,
        include_content: bool = True
    ) -> Dict:
        """
        Get single policy with full content.
        Reference: LLD 11 Section 3.4
        """
        try:
            url = f"{self.base_url}/v1/policies/{policy_id}"
            params = {"include_content": include_content}
            response = requests.get(url, params=params, timeout=self.timeout)

            if response.status_code == 200:
                # API already returns {"success": True, "policy": {...}}
                return response.json()
            elif response.status_code == 404:
                return {"success": False, "status_code": 404, "error": "Policy not found"}
            else:
                return {"success": False, "status_code": response.status_code, "error": f"HTTP {response.status_code}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching policy {policy_id}: {e}")
            return {"success": False, "status_code": 0, "error": str(e)}

    def create_policy(self, policy_data: Dict, operator_email: Optional[str] = None) -> Dict:
        """Create new agent policy. Reference: LLD 11 Section 3.1"""
        try:
            url = f"{self.base_url}/v1/policies"
            operator_context = _get_operator_context()
            if not operator_email:
                operator_email = operator_context['operator_email']

            headers = {"Content-Type": "application/json", "X-Operator-Email": operator_email}
            response = requests.post(url, json=policy_data, headers=headers, timeout=self.timeout)

            if response.status_code == 201:
                data = response.json()
                return {"success": True, "status_code": 201, "policy": data, "message": data.get("message", "Policy created successfully")}
            elif response.status_code in [400, 409]:
                error_data = response.json()
                return {"success": False, "status_code": response.status_code, "error": error_data.get("error"), "details": error_data.get("details", [])}
            else:
                return {"success": False, "status_code": response.status_code, "error": f"HTTP {response.status_code}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"Error creating policy: {e}")
            return {"success": False, "status_code": 0, "error": str(e)}

    def update_policy(self, policy_id: str, policy_data: Dict, operator_email: Optional[str] = None) -> Dict:
        """Update existing policy. Reference: LLD 11 Section 3.2"""
        try:
            url = f"{self.base_url}/v1/policies/{policy_id}"
            operator_context = _get_operator_context()
            if not operator_email:
                operator_email = operator_context['operator_email']

            headers = {"Content-Type": "application/json", "X-Operator-Email": operator_email}
            response = requests.put(url, json=policy_data, headers=headers, timeout=self.timeout)

            if response.status_code == 200:
                data = response.json()
                return {"success": True, "status_code": 200, "policy": data, "message": data.get("message", "Policy updated successfully")}
            elif response.status_code in [400, 403, 404]:
                error_data = response.json()
                return {"success": False, "status_code": response.status_code, "error": error_data.get("error"), "details": error_data.get("details", [])}
            else:
                return {"success": False, "status_code": response.status_code, "error": f"HTTP {response.status_code}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"Error updating policy {policy_id}: {e}")
            return {"success": False, "status_code": 0, "error": str(e)}

    def delete_policy(self, policy_id: str, operator_email: Optional[str] = None) -> Dict:
        """Soft delete policy. Reference: LLD 11 Section 3.3"""
        try:
            url = f"{self.base_url}/v1/policies/{policy_id}"
            operator_context = _get_operator_context()
            if not operator_email:
                operator_email = operator_context['operator_email']

            headers = {"X-Operator-Email": operator_email}
            response = requests.delete(url, headers=headers, timeout=self.timeout)

            if response.status_code == 200:
                data = response.json()
                return {"success": True, "status_code": 200, "message": data.get("message", "Policy disabled successfully")}
            elif response.status_code in [403, 404]:
                error_data = response.json()
                return {"success": False, "status_code": response.status_code, "error": error_data.get("error")}
            else:
                return {"success": False, "status_code": response.status_code, "error": f"HTTP {response.status_code}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"Error deleting policy {policy_id}: {e}")
            return {"success": False, "status_code": 0, "error": str(e)}


# Global client instance - initialized immediately but safely
try:
    security_controller_client = SecurityControllerClient()
except Exception as e:
    logger.error(f"Failed to initialize Security Controller client: {e}")
    security_controller_client = None


def _get_client():
    """Get or create the Security Controller client."""
    global security_controller_client
    if security_controller_client is None:
        security_controller_client = SecurityControllerClient()
    return security_controller_client


# ============================================================
# CACHED API WRAPPERS (Performance Optimization)
# ============================================================
# These wrapper functions add caching to frequently-called APIs
# to reduce load and improve dashboard responsiveness.

@st.cache_data(ttl=5, show_spinner=False)
def get_agents_cached() -> Dict:
    """
    Get list of all agents (cached for 5 seconds).
    
    Returns:
        Dict with agents list and total count
    """
    client = _get_client()
    return client.get_agents()


@st.cache_data(ttl=5, show_spinner=False)
def get_agent_details_cached(agent_id: str) -> Optional[Dict]:
    """
    Get agent details (cached for 5 seconds).
    
    Args:
        agent_id: Agent identifier
        
    Returns:
        Agent details dict or None
    """
    client = _get_client()
    return client.get_agent_details(agent_id)


@st.cache_data(ttl=5, show_spinner=False)
def get_agent_tools_cached(agent_id: str) -> Dict:
    """
    Get agent tools (cached for 5 seconds).
    
    Args:
        agent_id: Agent identifier
        
    Returns:
        Dict with tools list
    """
    client = _get_client()
    return client.get_agent_tools(agent_id)


@st.cache_data(ttl=5, show_spinner=False)
def get_policies_cached(agent_id: Optional[str] = None) -> Dict:
    """
    Get policies (cached for 5 seconds).
    
    Args:
        agent_id: Optional agent filter
        
    Returns:
        Dict with policies list
    """
    client = _get_client()
    return client.get_policies(agent_id=agent_id)


# Note: get_logs() is NOT cached because it needs real-time data
# and is filtered by many parameters (time, agent, decision, etc.)


# ============================================================
# Helper Functions and Caching
# ============================================================

@st.cache_data(ttl=5, show_spinner=False)
def get_sigma_rules_cached(status: Optional[str] = None, match_range: str = "24h") -> Dict:
    """
    Get Sigma rules (cached for 5 seconds).

    Args:
        status: Optional status filter
        match_range: Match-count time window (1h, 24h, 7d, 30d)

    Returns:
        Dict with rules list
    """
    client = _get_client()
    return client.get_sigma_rules(status=status, match_range=match_range)


@st.cache_data(ttl=5, show_spinner=False)
def get_metrics_cached(since: Optional[str] = None) -> Dict:
    """
    Get security metrics (cached for 5 seconds - needs to be fresh).

    Args:
        since: Optional time filter

    Returns:
        Dict with metrics
    """
    client = _get_client()
    return client.get_metrics(since=since)


# Note: get_logs() is NOT cached because it needs real-time data
# and is filtered by many parameters (time, agent, decision, etc.)
