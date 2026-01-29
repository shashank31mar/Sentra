"""
Scenario Data Models
Sentra MVP - Workstream 13, Task 1.1
"""

from pydantic import BaseModel
from typing import List, Optional


class AgentTargets(BaseModel):
    """Target agents for scenario execution"""
    self_hosted: List[str] = []
    bedrock: List[str] = []


class Prompt(BaseModel):
    """Individual test prompt"""
    id: str
    text: str
    expected_decision: str  # ALLOW | DENY | ROLLBACK
    expected_threat: str


class Scenario(BaseModel):
    """Security test scenario definition"""
    scenario_id: str
    name: str
    description: str
    mode: str  # continuous | manual
    interval: Optional[int] = None  # seconds between runs
    agents: AgentTargets
    prompts: List[Prompt]
