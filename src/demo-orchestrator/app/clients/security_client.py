"""
Security Controller Client
Sentra MVP - Workstream 13, Task 2.4
"""

import os
import logging
import httpx
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

SECURITY_CONTROLLER_URL = os.environ.get(
    "SECURITY_CONTROLLER_URL",
    "http://security-controller.sentra.internal:8080"
)


class SecurityControllerClient:
    """Client for querying Security Controller audit logs"""
    
    def __init__(self, base_url: str = None, timeout: float = 30.0):
        self.base_url = base_url or SECURITY_CONTROLLER_URL
        self.timeout = timeout
    
    async def query_logs(
        self,
        scenario_id: Optional[str] = None,
        hours: int = 24,
        agent_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Query audit logs from Security Controller
        
        Args:
            scenario_id: Filter by scenario ID (optional)
            hours: Time range in hours (default 24)
            agent_type: Filter by agent type (optional)
        
        Returns:
            List of audit log entries
        """
        try:
            # Convert hours to ISO timestamps
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(hours=hours)
            
            params = {
                "since": start_time.isoformat(),
                "until": end_time.isoformat(),
                "limit": 1000  # Get max logs for aggregation
            }
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/v1/logs",
                    params=params
                )
                response.raise_for_status()
                data = response.json()
                
                # Handle response format
                logs = []
                if isinstance(data, list):
                    logs = data
                elif isinstance(data, dict):
                    logs = data.get("logs", data.get("events", []))
                
                # Filter by agent_type if specified (client-side filter)
                if agent_type:
                    logs = [log for log in logs if log.get("agent_type") == agent_type]
                
                return logs
                
        except httpx.TimeoutException:
            logger.error("Timeout querying Security Controller logs")
            return []
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error querying logs: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Error querying Security Controller: {e}")
            return []
    
    async def get_latest_audit(
        self,
        session_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get latest audit entry for a session by querying logs
        
        Args:
            session_id: Session ID to look up
        
        Returns:
            Audit entry dict or None
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Query logs filtered by session_id
                response = await client.get(
                    f"{self.base_url}/v1/logs",
                    params={
                        "session_id": session_id,
                        "limit": 1
                    }
                )
                
                if response.status_code == 404:
                    return None
                
                response.raise_for_status()
                data = response.json()
                
                # Extract logs from response
                logs = []
                if isinstance(data, list):
                    logs = data
                elif isinstance(data, dict):
                    logs = data.get("logs", data.get("events", []))
                
                # Return the first (most recent) log entry
                if logs:
                    return logs[0]
                
                return None
                
        except Exception as e:
            logger.error(f"Error getting audit for session {session_id}: {e}")
            return None
    
    async def health_check(self) -> bool:
        """Check if Security Controller is healthy"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/v1/health")
                return response.status_code == 200
        except Exception:
            return False

    def get_agents(self, enrich: bool = False) -> Dict[str, Any]:
        """
        Get list of agents from Security Controller
        
        Args:
            enrich: If True, include runtime statistics (slower)
        
        Returns:
            Dict with agents array and total count
        """
        try:
            import httpx
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(
                    f"{self.base_url}/v1/agents",
                    params={"enrich": str(enrich).lower()}
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Error fetching agents: {e}")
            return {"agents": [], "total": 0}
