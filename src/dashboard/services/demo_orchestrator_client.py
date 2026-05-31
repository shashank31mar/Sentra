"""
Demo Orchestrator API Client
Sentra MVP - Workstream 14

Best Practices Applied:
- Uses settings for URL configuration
- Timeouts on all requests
- Proper error handling and logging
"""
import logging
import requests
from typing import List, Dict, Optional
from config.settings import settings

logger = logging.getLogger(__name__)

# Timeouts by operation type
REQUEST_TIMEOUT_FAST = 30  # seconds - for simple operations
REQUEST_TIMEOUT_SLOW = 60  # seconds - for comparison/aggregation queries (includes CloudWatch Insights)


class DemoOrchestratorClient:
    """Client for Demo Orchestrator API"""
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or settings.demo_orchestrator_url
    
    def fetch_scenarios(self) -> List[Dict]:
        """Fetch all scenarios from demo orchestrator"""
        try:
            response = requests.get(
                f"{self.base_url}/demo/scenarios",
                timeout=REQUEST_TIMEOUT_FAST
            )
            response.raise_for_status()
            return response.json().get("scenarios", [])
        except requests.Timeout:
            logger.error("Timeout fetching scenarios")
            raise
        except requests.RequestException as e:
            logger.error(f"Failed to fetch scenarios: {e}")
            raise
    
    def get_scenario_details(self, scenario_id: str) -> Dict:
        """Get detailed scenario configuration"""
        try:
            response = requests.get(
                f"{self.base_url}/demo/scenarios/{scenario_id}",
                timeout=REQUEST_TIMEOUT_FAST
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to get scenario {scenario_id}: {e}")
            raise
    
    def trigger_scenario(self, scenario_id: str) -> Dict:
        """Trigger scenario once"""
        try:
            response = requests.post(
                f"{self.base_url}/demo/scenarios/{scenario_id}/trigger",
                timeout=30  # Longer timeout for execution
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to trigger scenario {scenario_id}: {e}")
            raise
    
    def start_scenario(self, scenario_id: str) -> Dict:
        """Start continuous execution"""
        try:
            response = requests.post(
                f"{self.base_url}/demo/scenarios/{scenario_id}/start",
                timeout=REQUEST_TIMEOUT_FAST
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to start scenario {scenario_id}: {e}")
            raise
    
    def pause_scenario(self, scenario_id: str) -> Dict:
        """Pause continuous execution"""
        try:
            response = requests.post(
                f"{self.base_url}/demo/scenarios/{scenario_id}/pause",
                timeout=REQUEST_TIMEOUT_FAST
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to pause scenario {scenario_id}: {e}")
            raise
    
    def pause_all(self) -> Dict:
        """Pause all running scenarios"""
        try:
            response = requests.post(
                f"{self.base_url}/demo/scenarios/pause-all",
                timeout=REQUEST_TIMEOUT_FAST
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to pause all scenarios: {e}")
            raise
    
    def start_all_continuous(self) -> Dict:
        """Start all continuous-mode scenarios"""
        try:
            response = requests.post(
                f"{self.base_url}/demo/scenarios/start-all",
                timeout=REQUEST_TIMEOUT_FAST
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to start all scenarios: {e}")
            raise
    
    def get_comparison(self, hours: int = 1, scenario_id: Optional[str] = None, include_prompts: bool = False) -> Dict:
        """Get comparison metrics (uses longer timeout due to CloudWatch aggregation)"""
        try:
            params = {"hours": hours, "include_prompts": str(include_prompts).lower()}
            if scenario_id:
                params["scenario_id"] = scenario_id

            response = requests.get(
                f"{self.base_url}/demo/comparison",
                params=params,
                timeout=REQUEST_TIMEOUT_SLOW  # Longer timeout for aggregation queries
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to get comparison: {e}")
            raise
    
    def refresh_comparison_cache(self) -> Dict:
        """Clear comparison cache on demo orchestrator to force fresh data"""
        try:
            response = requests.post(
                f"{self.base_url}/demo/comparison/refresh",
                timeout=REQUEST_TIMEOUT_FAST
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to refresh comparison cache: {e}")
            raise


# Singleton instance
_client = None

def get_demo_client() -> DemoOrchestratorClient:
    """Get singleton demo orchestrator client"""
    global _client
    if _client is None:
        _client = DemoOrchestratorClient()
    return _client
