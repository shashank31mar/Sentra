"""
YAML Scenario Loader
Sentra MVP - Workstream 13, Task 1.2
"""

import os
import yaml
from pathlib import Path
from typing import List

from app.models.scenario import Scenario

# Default scenarios directory (can be overridden via env var)
SCENARIOS_DIR = Path(os.environ.get(
    'SCENARIOS_DIR',
    Path(__file__).parent.parent.parent / "scenarios"
))


def load_scenario(scenario_id: str) -> Scenario:
    """Load single scenario from YAML file"""
    file_path = SCENARIOS_DIR / f"{scenario_id}.yaml"
    
    if not file_path.exists():
        raise FileNotFoundError(f"Scenario '{scenario_id}' not found at {file_path}")
    
    with open(file_path, "r") as f:
        data = yaml.safe_load(f)
    
    return Scenario(**data)


def load_all_scenarios() -> List[Scenario]:
    """Load all scenario YAML files from scenarios directory"""
    scenarios = []
    
    if not SCENARIOS_DIR.exists():
        return scenarios
    
    for file_path in sorted(SCENARIOS_DIR.glob("*.yaml")):
        try:
            with open(file_path, "r") as f:
                data = yaml.safe_load(f)
                scenarios.append(Scenario(**data))
        except Exception as e:
            # Log but don't fail on individual scenario errors
            print(f"Warning: Failed to load {file_path}: {e}")
    
    return scenarios


def get_scenario_ids() -> List[str]:
    """Get list of available scenario IDs"""
    if not SCENARIOS_DIR.exists():
        return []
    
    return [f.stem for f in sorted(SCENARIOS_DIR.glob("*.yaml"))]
