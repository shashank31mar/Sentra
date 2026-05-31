"""
Scenario Data Models
Sentra MVP - Workstream 13, Task 1.1
Workstream 15 M5: cross-cloud fields added (azure_foundry agents + cross_cloud plan).
"""

from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional


class AgentTargets(BaseModel):
    """Target agents for scenario execution.

    `azure_foundry` was added in Workstream 15 M5. The demo orchestrator's
    executor does not invoke Azure agents directly — they are driven by the
    dashboard's cross-cloud scenario runner (Sentra/src/dashboard/components/
    cross_cloud_scenarios.py). The field is declared here so a YAML scenario
    can list its full cross-cloud target set in one place; the orchestrator
    just ignores it for now.
    """
    self_hosted: List[str] = []
    bedrock: List[str] = []
    azure_foundry: List[str] = []


class Prompt(BaseModel):
    """Individual test prompt"""
    id: str
    text: str
    expected_decision: str  # ALLOW | DENY | ROLLBACK
    expected_threat: str


class CrossCloudStep(BaseModel):
    """One step in a cross-cloud scenario timeline.

    Steps run in declaration order. Each step targets exactly one cloud and
    invokes one agent. The runner generates a single session_id for the whole
    scenario so cross-cloud preconditions (LLD 15 §4.5) can be evaluated by
    the controller's context validator.

    Exactly one of `tool` or `prompt` should be set:
      - `tool` + `tool_params`: direct tool invocation through the cloud's
        interceptor (used for the Azure side and for AWS Action-Group fast
        paths). Bypasses the LLM.
      - `prompt`: natural-language prompt — the LLM decides which tools to
        call. Used when the scenario depends on agent reasoning.
    """
    id: str
    cloud: str  # "bedrock" | "azure_foundry"
    agent_id: str
    tool: Optional[str] = None
    tool_params: Dict[str, Any] = Field(default_factory=dict)
    prompt: Optional[str] = None
    # user_input carried in the ValidationRequest's `user_input` field — used
    # by Sentra's sigma engine. Lets a tool-step YAML express attack payloads
    # (e.g., SQL injection) in user_input even when tool_params look benign.
    # Defaults to step.description (or a placeholder) when absent.
    user_input: Optional[str] = None
    expected_decision: str           # ALLOW | DENY
    expected_reason_contains: Optional[str] = None
    # Pin which layer is *expected* to produce the decision. The dashboard
    # runner flags FAILED if the right verdict came from the wrong layer
    # (e.g., Azure content filter caught it when Sentra was supposed to).
    # Values: "sentra" | "azure_content_filter" | "bedrock_guardrail" | "agent_self_refusal"
    expected_source: Optional[str] = None
    description: Optional[str] = None
    # Workstream 18 / LLD 18 §4.4 — per-step intent. Validator (M3) hard-errors
    # on misuse (intent=enforcement + prompt: without allow_llm_path; intent=
    # threat_detection + tool:). Optional on pre-WS18 scenarios; required on new.
    intent: Optional[str] = None  # "enforcement" | "threat_detection"
    allow_llm_path: bool = False


class CrossCloudPlan(BaseModel):
    """Cross-cloud scenario definition consumed by the dashboard's runner.

    The orchestrator's executor ignores this — the orchestrator runs the
    AWS-only `prompts` list as it always has. The dashboard reads
    `cross_cloud` and drives the multi-cloud workflow.

    Workstream 15 M5; see Sentra/src/dashboard/components/cross_cloud_scenarios.py.
    """
    story: str                       # one-sentence investor story
    steps: List[CrossCloudStep]
    outcome_template: Optional[str] = None  # f-string-style summary, e.g. "Blocked {deny_count} of {total} attacks"


class Scenario(BaseModel):
    """Security test scenario definition"""
    scenario_id: str
    name: str
    description: str
    mode: str  # continuous | manual
    interval: Optional[int] = None  # seconds between runs
    agents: AgentTargets
    prompts: List[Prompt] = []
    # Workstream 15 M5: optional; absence means this is an AWS-only scenario
    # the orchestrator can run normally.
    cross_cloud: Optional[CrossCloudPlan] = None
