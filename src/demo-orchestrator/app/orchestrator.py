"""
Demo Orchestrator - Continuous Scheduler
Sentra MVP - Workstream 13, Task 2.3
"""

import asyncio
import logging
from typing import Dict, Optional
from datetime import datetime

from app.utils.yaml_loader import load_scenario, load_all_scenarios
from app.executor import ScenarioExecutor
from app.models.scenario import Scenario

logger = logging.getLogger(__name__)


class DemoOrchestrator:
    """
    Manages continuous and on-demand scenario execution
    
    Features:
    - Start/pause continuous execution per scenario
    - Manual trigger for immediate execution
    - Track running scenarios and their status
    """
    
    def __init__(self):
        self.running_scenarios: Dict[str, asyncio.Task] = {}
        self.scenario_status: Dict[str, Dict] = {}
        self.executor = ScenarioExecutor()
    
    async def start_continuous(self, scenario_id: str) -> Dict:
        """
        Start scenario in continuous loop
        
        Args:
            scenario_id: Scenario to start
        
        Returns:
            Status dict
        """
        if scenario_id in self.running_scenarios:
            return {
                "status": "already_running",
                "scenario_id": scenario_id,
                "message": f"Scenario {scenario_id} is already running"
            }
        
        try:
            scenario = load_scenario(scenario_id)
        except FileNotFoundError:
            return {
                "status": "error",
                "scenario_id": scenario_id,
                "message": f"Scenario {scenario_id} not found"
            }
        
        if scenario.mode != "continuous":
            return {
                "status": "error",
                "scenario_id": scenario_id,
                "message": f"Scenario {scenario_id} is not configured for continuous mode"
            }
        
        # Create background task
        task = asyncio.create_task(
            self._continuous_loop(scenario),
            name=f"scenario-{scenario_id}"
        )
        self.running_scenarios[scenario_id] = task
        self.scenario_status[scenario_id] = {
            "status": "running",
            "started_at": datetime.utcnow().isoformat(),
            "interval": scenario.interval,
            "run_count": 0,
            "last_run": None,
            "last_error": None
        }
        
        logger.info(
            f"Started continuous scenario",
            extra={
                "scenario_id": scenario_id,
                "interval": scenario.interval
            }
        )
        
        return {
            "status": "started",
            "scenario_id": scenario_id,
            "interval": scenario.interval,
            "message": f"Scenario {scenario_id} started (interval: {scenario.interval}s)"
        }
    
    async def _continuous_loop(self, scenario: Scenario):
        """Background loop for continuous execution"""
        scenario_id = scenario.scenario_id
        
        while scenario_id in self.running_scenarios:
            try:
                logger.info(f"Executing continuous scenario: {scenario_id}")
                
                result = await self.executor.execute(scenario)
                
                # Update status
                if scenario_id in self.scenario_status:
                    self.scenario_status[scenario_id]["run_count"] += 1
                    self.scenario_status[scenario_id]["last_run"] = datetime.utcnow().isoformat()
                    self.scenario_status[scenario_id]["last_run_id"] = result.get("run_id")
                
                logger.info(
                    f"Continuous scenario completed",
                    extra={
                        "scenario_id": scenario_id,
                        "run_id": result.get("run_id"),
                        "duration_ms": result.get("duration_ms")
                    }
                )
                
                # Wait for next interval
                await asyncio.sleep(scenario.interval)
                
            except asyncio.CancelledError:
                logger.info(f"Scenario {scenario_id} cancelled")
                break
            except Exception as e:
                logger.error(
                    f"Error in continuous loop for {scenario_id}: {e}",
                    exc_info=True
                )
                
                # Update error status
                if scenario_id in self.scenario_status:
                    self.scenario_status[scenario_id]["last_error"] = str(e)
                
                # Back off on error
                await asyncio.sleep(60)
    
    async def pause_continuous(self, scenario_id: str) -> Dict:
        """
        Pause continuous execution
        
        Args:
            scenario_id: Scenario to pause
        
        Returns:
            Status dict
        """
        if scenario_id not in self.running_scenarios:
            return {
                "status": "not_running",
                "scenario_id": scenario_id,
                "message": f"Scenario {scenario_id} is not running"
            }
        
        # Cancel the task
        task = self.running_scenarios[scenario_id]
        task.cancel()
        
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        # Clean up
        del self.running_scenarios[scenario_id]
        
        if scenario_id in self.scenario_status:
            self.scenario_status[scenario_id]["status"] = "paused"
            self.scenario_status[scenario_id]["paused_at"] = datetime.utcnow().isoformat()
        
        logger.info(f"Paused continuous scenario: {scenario_id}")
        
        return {
            "status": "paused",
            "scenario_id": scenario_id,
            "message": f"Scenario {scenario_id} paused"
        }
    
    async def pause_all(self) -> Dict:
        """Pause all running scenarios"""
        paused = []
        
        for scenario_id in list(self.running_scenarios.keys()):
            result = await self.pause_continuous(scenario_id)
            paused.append(result)
        
        return {
            "status": "completed",
            "paused_count": len(paused),
            "scenarios": paused
        }
    
    async def trigger_once(self, scenario_id: str) -> Dict:
        """
        Execute scenario immediately, one time
        
        Args:
            scenario_id: Scenario to execute
        
        Returns:
            Execution result
        """
        try:
            scenario = load_scenario(scenario_id)
        except FileNotFoundError:
            return {
                "status": "error",
                "scenario_id": scenario_id,
                "message": f"Scenario {scenario_id} not found"
            }
        
        result = await self.executor.execute(scenario)
        
        return {
            "status": "completed",
            **result
        }
    
    def get_status(self, scenario_id: Optional[str] = None) -> Dict:
        """
        Get status of scenarios
        
        Args:
            scenario_id: Specific scenario (optional)
        
        Returns:
            Status dict
        """
        if scenario_id:
            if scenario_id in self.scenario_status:
                return self.scenario_status[scenario_id]
            elif scenario_id in self.running_scenarios:
                return {"status": "running"}
            else:
                return {"status": "stopped"}
        
        return {
            "running": list(self.running_scenarios.keys()),
            "running_count": len(self.running_scenarios),
            "scenarios": self.scenario_status
        }
    
    async def start_all_continuous(self) -> Dict:
        """Start all continuous-mode scenarios"""
        started = []
        
        scenarios = load_all_scenarios()
        for scenario in scenarios:
            if scenario.mode == "continuous":
                result = await self.start_continuous(scenario.scenario_id)
                started.append(result)
        
        return {
            "status": "completed",
            "started_count": len(started),
            "scenarios": started
        }


# Global orchestrator instance
_orchestrator: Optional[DemoOrchestrator] = None


def get_orchestrator() -> DemoOrchestrator:
    """Get or create global orchestrator instance"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = DemoOrchestrator()
    return _orchestrator
